from collections import namedtuple

import numpy
from tensorflow.python.keras.engine.input_layer import InputLayer
from tqdm import tqdm

GraphNode = namedtuple('GraphNode', ['layer', 'spatial_location'])
Dependency = namedtuple('Dependency', ['input_index', 'spatial_location'])

NONE_INT_VALUE = -1


class DependencyGraph(object):
    """docstring for DependencyGraph
    we Need this custom class instead of existing graphs libraries such as networkx because in deep models (depth ~20)
    theirs topological_sort is very slow (probably because of inefficient memory usage)
    """

    def __init__(self, keras_model, default_max_number_of_outgoing_edges=10):
        super(DependencyGraph, self).__init__()
        self.default_max_number_of_outgoing_edges = default_max_number_of_outgoing_edges
        self.keras_model = keras_model
        self._create_vertices()

    def _create_vertices(self):
        self._outgoing_edges_spatial_index = {}
        self._outgoing_edges_layer_index = {}
        self._outgoing_edges_counter = {}
        self._incoming_edges_counter = {}
        self._incoming_edges_dfs_status = {}
        self._layer_to_layer_index = {}
        self._layers_shape = {}
        self.vertices_counter = 0
        for idx, layer in enumerate(self.keras_model.layers):
            self.vertices_counter += self._create_layer_vertices(layer)
            self._layer_to_layer_index[layer] = idx
        self._queue_spatial_index = numpy.full((self.vertices_counter, ), NONE_INT_VALUE)
        self._queue_layer_index = numpy.full((self.vertices_counter, ), NONE_INT_VALUE)
        self._queue_len = 0

    def _create_layer_vertices(self, layer):
        output_shape = layer.output_shape
        if isinstance(layer, InputLayer):
            # we assume the last dim is channels dim in every layer
            output_shape = output_shape + (1,)
        self._layers_shape[layer] = output_shape[1:-1]
        spatial_size = numpy.prod(self._layers_shape[layer])
        self._outgoing_edges_spatial_index[layer] = numpy.full(
            (spatial_size, self.default_max_number_of_outgoing_edges),
            NONE_INT_VALUE, dtype=numpy.int32)
        self._outgoing_edges_layer_index[layer] = numpy.full((spatial_size, self.default_max_number_of_outgoing_edges),
                                                             NONE_INT_VALUE, dtype=numpy.int32)
        self._outgoing_edges_counter[layer] = numpy.zeros((spatial_size,),
                                                          dtype=numpy.int32)
        self._incoming_edges_counter[layer] = numpy.zeros((spatial_size,),
                                                          dtype=numpy.int32)
        self._incoming_edges_dfs_status[layer] = numpy.zeros((spatial_size,),
                                                             dtype=numpy.int32)
        return spatial_size

    def _increase_layer_num_of_edges(self, layer):
        old_incoming_edges_spatial_index_arr = self._outgoing_edges_spatial_index[layer]
        old_incoming_edges_layer_index_arr = self._outgoing_edges_layer_index[layer]
        spatial_size = old_incoming_edges_spatial_index_arr.shape[0]
        max_number_of_incoming_edges = old_incoming_edges_spatial_index_arr.shape[1]
        self._outgoing_edges_spatial_index[layer] = numpy.full((spatial_size, max_number_of_incoming_edges * 2),
                                                               NONE_INT_VALUE, dtype=numpy.int32)
        self._outgoing_edges_layer_index[layer] = numpy.full((spatial_size, max_number_of_incoming_edges * 2),
                                                             NONE_INT_VALUE, dtype=numpy.int32)
        self._outgoing_edges_spatial_index[layer][:,
        :max_number_of_incoming_edges] = old_incoming_edges_spatial_index_arr
        self._outgoing_edges_layer_index[layer][:, :max_number_of_incoming_edges] = old_incoming_edges_layer_index_arr

    def _get_layer_index(self, vertex):
        return self._layer_to_layer_index[vertex.layer]

    def _get_spatial_index(self, vertex):
        res = vertex.spatial_location[-1]
        prev_dim_factor = 1
        for prev_dim_size, dim_location in zip(self._layers_shape[vertex.layer][::-1][:-1],
                                               vertex.spatial_location[::-1][1:]):
            prev_dim_factor *= prev_dim_size
            res += dim_location * prev_dim_factor
        return res

    def _spatial_index_to_location(self, spatial_index, layer_index):
        dims_location = []
        for dim_size in self._layers_shape[self.keras_model.layers[layer_index]][::-1]:
            dims_location.append(spatial_index % dim_size)
            spatial_index = spatial_index // dim_size
        return tuple(dims_location[::-1])

    def add_edge(self, from_vertex, to_vertex):
        to_vertex_spatial_index = self._get_spatial_index(to_vertex)
        to_vertex_layer_index = self._get_layer_index(to_vertex)
        from_vertex_spatial_index = self._get_spatial_index(from_vertex)
        edge_index = self._outgoing_edges_counter[from_vertex.layer][from_vertex_spatial_index]
        self._outgoing_edges_counter[from_vertex.layer][from_vertex_spatial_index] += 1
        self._incoming_edges_counter[to_vertex.layer][to_vertex_spatial_index] += 1
        if self._outgoing_edges_layer_index[from_vertex.layer].shape[-1] <= edge_index:
            self._increase_layer_num_of_edges(from_vertex.layer)
        self._outgoing_edges_spatial_index[from_vertex.layer][
            from_vertex_spatial_index, edge_index] = to_vertex_spatial_index
        self._outgoing_edges_layer_index[from_vertex.layer][
            from_vertex_spatial_index, edge_index] = to_vertex_layer_index

    def topological_sort(self):
        print('start topological_sort')
        results = []
        visited_nodes_counter = 0
        self._reset_dfs_status()
        self._add_vertices_with_zero_incoming_degree_to_queue()
        with tqdm(total=self.vertices_counter) as progress_bar:
            while self._queue_len > 0:
                layer_index = self._queue_layer_index[self._queue_len - 1]
                layer = self.keras_model.layers[layer_index]
                spatial_index = self._queue_spatial_index[self._queue_len - 1]
                spatial_location = self._spatial_index_to_location(spatial_index, layer_index)
                results.append(GraphNode(layer=layer, spatial_location=spatial_location))
                visited_nodes_counter += 1
                progress_bar.update(visited_nodes_counter)
                self._queue_len -= 1
                self._decrease_incoming_edge_counter_from_node_neighbors(layer, spatial_index)
        if visited_nodes_counter != self.vertices_counter:
            raise Exception('Dependency graph has cycle, invalid autoregressive model')
        print('finish topological_sort')
        return results

    def _decrease_incoming_edge_counter_from_node_neighbors(self, layer, spatial_index):
        for i in range(self._outgoing_edges_counter[layer][spatial_index]):
            to_layer_index = self._outgoing_edges_layer_index[layer][spatial_index, i]
            to_layer = self.keras_model.layers[to_layer_index]
            to_spatial_index = self._outgoing_edges_spatial_index[layer][spatial_index, i]
            self._incoming_edges_dfs_status[to_layer][to_spatial_index] -= 1
            if self._incoming_edges_dfs_status[to_layer][to_spatial_index] == 0:
                self._queue_layer_index[self._queue_len] = to_layer_index
                self._queue_spatial_index[self._queue_len] = to_spatial_index
                self._queue_len += 1

    def _reset_dfs_status(self):
        self._queue_len = 0
        for layer, incoming_edges_counter in self._incoming_edges_counter.items():
            self._incoming_edges_dfs_status[layer][:] = incoming_edges_counter[:]

    def _add_vertices_with_zero_incoming_degree_to_queue(self):
        for layer, incoming_edges_counter in self._incoming_edges_dfs_status.items():
            layer_index = self._layer_to_layer_index[layer]
            for i in range(incoming_edges_counter.shape[0]):
                if incoming_edges_counter[i] == 0:
                    self._queue_layer_index[self._queue_len] = layer_index
                    self._queue_spatial_index[self._queue_len] = i
                    self._queue_len += 1
