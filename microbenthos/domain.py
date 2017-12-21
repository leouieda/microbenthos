"""
Module that defines the microbial mat domain and related environmental parameters
"""

import logging

from fipy import PhysicalField, CellVariable, Variable
from fipy.meshes.uniformGrid1D import UniformGrid1D
from fipy.tools import numerix


class SedimentDBLDomain(object):
    """
    Class for the MicromatModelBase that defines the mesh for the domain, which includes a
    sediment column of atleast 10 cells and an optional Diffusive boundary layer column.

    Note: The domain dimensions are converted into SI units (meters) for the creation of the mesh,
    so that the model equations and parameters can all work on a common dimension system.
    """

    def __init__(self, cell_size = 0.1, sediment_length = 10, dbl_length = 1, porosity = 0.6):
        """
        Create a model domain that defines a sediment column and a diffusive boundary layer
        column on top of it. The mesh parameters should be supplied.

        If the mesh dimensions are given as :class:`PhysicalField` then they are converted into
        meters. If plain numbers (float) are given, then they are interpreted as being in units
        of mm.

        Args:
            cell_size: The size of a cell (default: 100 micron)
            sediment_length: The length of the sediment column (default: 1 cm)
            dbl_length: The length of the DBL (default: 1 mm)
            porosity: The porosity value for the sediment column

        """
        self.logger = logging.getLogger(__name__)
        self.VARS = {}
        self.mesh = None
        self.sediment_Ncells = self.DBL_Ncells = None

        self.cell_size = PhysicalField(cell_size, 'mm')
        self.sediment_length = PhysicalField(sediment_length, 'mm')
        self.DBL_length = PhysicalField(dbl_length, 'mm')

        assert self.sediment_length.numericValue > 0, "Sediment length should be positive"
        assert self.DBL_length.numericValue >= 0, "DBL length should be positive or zero"

        assert (self.sediment_length / self.cell_size) >= 10, \
            "Sediment length {} too small for cell size {}".format(
                self.sediment_length, self.cell_size
                )

        self.sediment_Ncells = int(self.sediment_length / self.cell_size)
        self.DBL_Ncells = int(self.DBL_length / self.cell_size)
        self.domain_Ncells = self.sediment_Ncells + self.DBL_Ncells

        self.sediment_length = self.sediment_Ncells * self.cell_size
        self.DBL_length = self.sediment_interface = self.DBL_Ncells * self.cell_size
        self.domain_length = self.sediment_length + self.DBL_length

        self.idx_surface = self.DBL_Ncells

        self.create_mesh()
        self.set_porosity(float(porosity))

    def __str__(self):
        return 'Domain(mesh={}, sed={}, DBL={})'.format(self.mesh, self.sediment_Ncells,
                                                        self.DBL_Ncells)

    def __repr__(self):
        return 'SedimentDBLDomain(cell_size={:.2}, sed_length={:.2}, dbl_length={:.2})'.format(
            self.cell_size.value, self.sediment_length.value, self.DBL_length.value
            )

    def __getitem__(self, item):
        return self.VARS[item]

    def create_mesh(self):
        """
        Create the mesh for the domain
        """

        self.logger.info('Creating UniformGrid1D with {} sediment and {} DBL cells of {}'.format(
            self.sediment_Ncells, self.DBL_Ncells, self.cell_size
            ))
        self.mesh = UniformGrid1D(dx=self.cell_size.numericValue,
                                  nx=self.domain_Ncells,
                                  )
        self.logger.debug('Created domain mesh: {}'.format(self.mesh))
        self.distances = Variable(value=self.mesh.scaledCellDistances[:-1], unit='m')
        Z = self.mesh.x()
        Z = Z - Z[self.idx_surface]
        self.depths_um = Z * 1e6 # in micrometers, with 0 at surface

    def create_var(self, name, **kwargs):
        """
        Create a variable on the domain as a :class:`CellVariable`.

        If a `value` is not supplied, then it is set to 0.0. Before creating the cell variable,
        the value is multiplied with an array of ones of the shape of the domain mesh. This
        ensures that no single-valued options end up creating an improper variable. As a result,
        several types for `value` are valid.

        Args:
            name (str): The name identifier for the variable
            value (int, float, array, PhysicalField): value to set on the variable
            unit (str): The physical units for the variable
            hasOld (bool): Whether the variable maintains the older values, useful during
            numerical computations.
            **kwargs: passed to the call to :class:`CellVariable`

        Returns:
            The created variable

        Raises:
            ValueError: If `name` is not a string with len > 0
            ValueError: If value has a shape incompatible with the mesh
            RuntimeError: If domain variable with same name already exists
        """

        self.logger.info('Creating domain variable {!r}'.format(name))
        if not self.mesh:
            raise RuntimeError('Cannot create cell variable without mesh!')

        if not name:
            raise ValueError('Name must have len > 0')

        if name in self.VARS:
            # self.logger.warning('Variable {} already exists. Over-writing with new'.format(vname))
            raise RuntimeError('Domain variable {} already exists!'.format(name))

        if kwargs.get('value') is None:
            self.logger.debug('Cannot set {} to None. Setting to zero instead!'.format(name))
            kwargs['value'] = 0.0

        value = kwargs.pop('value')

        if hasattr(value, 'shape'):
            if value.shape not in ((), self.mesh.shape):
                raise ValueError('Value shape {} not compatible for mesh {}'.format(value.shape,
                                                                                    self.mesh.shape))
        unit = kwargs.get('unit')
        if unit and isinstance(value, PhysicalField):
            vunit = str(value.unit.name())
            if vunit != "1":
                # value has units
                self.logger.warning('{!r} value has units {!r}, which will override '
                                    'supplied {}'.format(name, vunit, unit))

        try:
            varr = numerix.ones(self.mesh.shape, dtype='float32')
            value *= varr
        except TypeError:
            raise ValueError('Value {} could not be cast numerically'.format(value))

        self.logger.debug('Creating CellVariable {!r} with: {}'.format(name, kwargs))
        var = CellVariable(mesh=self.mesh, name=name, value=value, **kwargs)

        self.logger.debug('Created variable {!r}: shape: {} unit: {}'.format(var,
                                                                               var.shape, var.unit))
        self.VARS[name] = var
        return var

    def var_in_sediment(self, vname):
        """
        Convenience method to get the value of domain variable in the sediment
        Args:
            vname: Name of the variable

        Returns:
            Slice of the variable in the sediment

        """
        return self.VARS[vname][self.idx_surface:]

    def var_in_DBL(self, vname):
        """
        Convenience method to get the value of domain variable in the DBL

        Args:
            vname: Name of the variable

        Returns:
            Slice of the variable in the DBL

        """
        return self.VARS[vname][:self.idx_surface]

    def set_porosity(self, porosity):
        """
        Set the porosity for the sediment region. The DBL porosity is set to 1.0

        Args:
            porosity: A value for porosity between 0 and 1

        Returns:
            The instance of the porosity variable

        """
        if not (0.1 < porosity < 0.9):
            raise ValueError(
                'Sediment porosity={} should be between (0.1, 0.9)'.format(porosity))

        P = self.VARS.get('porosity')
        if P is None:
            P = self.create_var('porosity', value=1.0)

        self.sediment_porosity = float(porosity)
        P[:self.idx_surface] = 1.0
        P[self.idx_surface:] = self.sediment_porosity
        self.logger.info('Set sediment porosity to {} and DBL porosity to 1.0'.format(
            self.sediment_porosity))
        return P
