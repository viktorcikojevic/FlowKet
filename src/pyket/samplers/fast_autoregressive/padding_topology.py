from .data_structures import Dependency
from .layer_topology import LayerTopology
from .topology_manager import TopologyManager
from ...layers import PeriodicPadding

from tensorflow.keras.layers import ZeroPadding1D, ZeroPadding2D, ZeroPadding3D


class PaddingTopology(LayerTopology):
    """docstring for PaddingTopology"""

    def __init__(self, layer):
        super(PaddingTopology, self).__init__(layer)
        self.padding = self.layer.padding
        if not isinstance(self.padding[0], tuple):
            self.padding = (self.padding, )
        self.prefix_padding = tuple([dim[0] for dim in self.padding])

    def apply_layer_for_single_spatial_location(self, spatial_location, dependencies_values):
        return dependencies_values[0]

    def get_spatial_dependency(self, spatial_location):
        for location, (prefix, _), input_shape in \
                zip(spatial_location, self.padding, self.layer.input_shape[1:-1]):
            if location < prefix or location - prefix >= input_shape:
                return []
        shifted_spatial_location = tuple([location - padding for location, padding in
                                          zip(spatial_location, self.prefix_padding)])
        return [Dependency(input_index=0, spatial_location=shifted_spatial_location)]


class PeriodicPaddingTopology(LayerTopology):
    """docstring for PeriodicPaddingTopology"""

    def __init__(self, layer):
        super(PeriodicPaddingTopology, self).__init__(layer)
        self.padding = self.layer.padding

    def apply_layer_for_single_spatial_location(self, spatial_location, dependencies_values):
        return dependencies_values[0]

    def get_spatial_dependency(self, spatial_location):
        shifted_spatial_location = tuple([(location - padding) % input_shape for location, padding, input_shape in
                                          zip(spatial_location, self.padding, self.layer.input_shape[1:-1])])
        return [Dependency(input_index=0, spatial_location=shifted_spatial_location)]


TopologyManager().register_layer_topology(PaddingTopology, ZeroPadding1D)
TopologyManager().register_layer_topology(PaddingTopology, ZeroPadding2D)
TopologyManager().register_layer_topology(PaddingTopology, ZeroPadding3D)
TopologyManager().register_layer_topology(PeriodicPaddingTopology, PeriodicPadding)