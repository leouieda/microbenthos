import importlib
import logging

from fipy import PhysicalField
from fipy.tools import numerix

from microbenthos.utils.snapshotters import snapshot_var


class Entity(object):
    def __init__(self, logger = None):

        if not logger:
            self.logger = logging.getLogger(__name__)
            self.logger.warning('No logger supplied, creating in base class: {}'.format(__name__))
        else:
            self.logger = logger

    @classmethod
    def from_params(cls_, cls, init_params, post_params = None):
        """
        Create entity instance from supplied CLS path and init parameters

        CLS is a string such as `Irradiance` or `microbenthos.Process` or `sympy.Lambda`

        Args:
            cls (str): The qualified `module.class_name`. If no `module` is in the string,
            then it is assummed to be `"microbenthos"`

            init_params (dict): Dictionary of params to supply to the class __init__

            post_params (dict): Dictionary of params for :meth:`post_init` if available

        Returns:
            Instance of the entity

        """
        logger = logging.getLogger(__name__)
        logger.debug('Setting up entity from cls: {}'.format(cls))
        try:
            cls_modname, cls_name = cls.rsplit('.', 1)
        except ValueError:
            # raise ValueError('Path {} could not be split into module & class'.format(cls))
            # this is then just a class name to import from microbenthos
            cls_modname = 'microbenthos'
            cls_name = cls

        try:
            # logger.debug('Importing {}'.format(cls_modname))
            cls_module = importlib.import_module(cls_modname)
            CLS = getattr(cls_module, cls_name)
            logger.debug('Using class: {}'.format(CLS))
        except (ImportError, AttributeError):
            raise TypeError('Class {} in {} could not be found!'.format(cls_name, cls_modname))

        logger.debug('Init params: {}'.format(init_params))
        inst = CLS(**init_params)

        post_params = post_params or {}

        if hasattr(inst, 'post_init'):
            # logger.debug("Calling post_init for instance: {}".format(post_params))
            inst.post_init(**post_params)

        logger.debug('Created entity: {}'.format(inst))
        return inst

    @classmethod
    def from_dict(cls, cdict):
        """
        Create the entity instance from a supplied dictionary of parameters.

        Args:
            cdict: This dictionary must contain a key `cls` which contains the import path to the
            class (example: `"microbenthos.irradiance.Irradiance"`, and a key `init_params` whose
            value
            will be passed to the constructor of the class. The rest of the dictionary (except
            `cls`) will be
            passed to :meth:`.post_init` to allow subclasses to finish setup.

        Returns:
            New instance of the entity

        Raises:
              KeyError: If the `cls` key is missing
              ValueError: If the cls is not a valid module path
              TypeError: If the class cannot be imported
        """
        try:
            cls_path = cdict.pop('cls')
        except KeyError:
            raise KeyError('Config dict missing required key "cls"!')

        init_params = cdict.get('init_params', {})
        post_params = cdict.get('post_params', {})

        return cls.from_params(cls=cls_path, init_params=init_params, post_params=post_params)

    def post_init(self, **kwargs):
        """
        Hook to customize initialization of entity after construction by :meth:`.from_dict`. This
        must be overriden by subclasses, to be useful.

        Args:
            **kwargs:

        Returns:
            None
        """
        # self.logger.debug('Empty post_init on {}'.format(self))

    def update_time(self, clocktime):
        """
        Method which should update the entity features for the simulation clocktime

        :param float clocktime: The simulation time (units depends on the solver setup)
        """
        self.logger.debug('Updating {} for clocktime {}'.format(self, clocktime))

    def snapshot(self):
        """
        Returns a snapshot of the entity's state

        Returns:
            Dictionary with keys: `data`, `metadata, where the value of each `data` entry is
            either another such dictionary or a numeric array
        """
        raise NotImplementedError('Snapshot of entity {}'.format(self))

    __getstate__ = snapshot


class DomainEntity(Entity):
    """
    A base class that represents entities in the microbenthic env. This can be used to
    subclass microbial groups, chemical reactions, or other parameters. The class provides a
    uniform interface to add the entity to the simulation domain and setup parameters and update
    according to the simulation clock.
    """

    def __init__(self, **kwargs):

        super(DomainEntity, self).__init__(**kwargs)
        self._domain = None

    @property
    def domain(self):
        """
        Set the domain for the entity

        Args:
             domain: An instance of :class:`SedimentDBLDomain`

        Raises:
            RuntimeError: if domain is already set
            TypeError: if domain is of wrong type

        """
        return self._domain

    @domain.setter
    def domain(self, domain):
        if domain is None:
            return

        if self.domain:
            raise RuntimeError(
                '{} already has a domain. Cannot set again!'.format(self))

        self._domain = domain
        self.logger.debug('Added to domain: {}'.format(self))
        self.on_domain_set()

    def set_domain(self, domain):
        self.domain = domain

    def check_domain(self):
        if not self.has_domain:
            raise RuntimeError('Domain required for setup of {}'.format(self))
        return True

    @property
    def has_domain(self):
        return self.domain is not None

    def on_domain_set(self):
        """
        Hook for when a domain is set

        To be used by sub-classes to setup sub-entities

        """

    def setup(self, **kwargs):
        """
        Method to set up the mat entity once a domain is available

        This may include logic to add any featuers it has also to the domain.

        To be overridden by subclasses
        """
        self.logger.debug('Setup empty: {}'.format(self))

    @property
    def is_setup(self):
        """
        A flag to indicate if an entity still needs setting up

        Must be overriden by subclasses to be useful
        """
        return True


class Variable(DomainEntity):
    """
    A helper class to represent a variable for the model domain, which can create the variable,
    apply boundary conditions.
    """

    def __init__(self, name, create,
                 constraints = None,
                 seed = None,
                 **kwargs):
        """
        Configure the creation of a variable and its boundary conditions

        Args:
            name (str): The name of the variable
            create (dict): parameters for variable creation (see :meth:`.create`)
            constraints (dict): Mapping of `location` to value of boundary condition
            through :meth:`.constrain`.
            seed (dict): parameters to seed initial value of variable
            **kwargs:
        """
        self.logger = kwargs.get('logger') or logging.getLogger(__name__)
        kwargs['logger'] = self.logger
        super(Variable, self).__init__(**kwargs)

        self.logger.debug('Init in DomainVariable for {!r}'.format(name))
        self.name = name
        self.var = None

        self.create_params = create

        self.check_create(**self.create_params)

        self.constraints = constraints or dict()
        self.check_constraints(self.constraints)

        self.seed_params = seed or dict()

    def __repr__(self):
        return 'Var({})'.format(self.name)

    @staticmethod
    def check_create(**params):

        name = params.get('name')
        if name:
            raise ValueError('Create params should not contain name. Will be set from init name.')

        from fipy import PhysicalField
        unit = params.get('unit')
        if unit:
            try:
                p = PhysicalField(1, params['unit'])
            except:
                raise ValueError('{!r} is not a valid unit!'.format(params['unit']))

    @staticmethod
    def check_constraints(constraints):
        """
        Check that constraints is a mapping of location to value of boundary conditions.
        Recognized location values are: `"top", "bottom"`.

        Raises:
            TypeError if `constraints` is not a mapping
            ValueError if `loc` is not valid
            ValueError if `value` is not single-valued

        """
        logger = logging.getLogger(__name__)

        locs = ('top', 'bottom', 'dbl', 'sediment')
        try:
            for loc, val in dict(constraints).items():
                pass
        except (ValueError, TypeError):
            logger.error('Constraints not a mapping of pairs: {}'.format(constraints))
            raise ValueError('Constraints should be mapping of (location, value) pairs!')

        for loc, val in dict(constraints).items():
            if loc not in locs:
                raise ValueError('Constraint loc={!r} unknown. Should be in {}'.format(
                    loc, locs
                    ))
            try:
                if isinstance(val, PhysicalField):
                    v = float(val.value)
                else:
                    v = float(val)
            except:
                raise ValueError('Constraint should be single-valued, not {!r}'.format(val))

    def setup(self, **kwargs):
        """
        Once a domain is available, create the variable with the requested parameters and apply
        any constraints.

        Returns:
            Instance of the variable created

        """

        self.check_domain()

        self.create(**self.create_params)

        if self.seed_params:
            self.seed(profile=self.seed_params['profile'], **self.seed_params['params'])
            if self.create_params.get('hasOld'):
                self.var.updateOld()

        self._LOCs = {
            'top': self.domain.mesh.facesLeft,
            'bottom': self.domain.mesh.facesRight,
            'dbl': slice(0, self.domain.idx_surface),
            'sediment': slice(self.domain.idx_surface, None)
            }

        invalid_pairs = [('top', 'dbl'), ('bottom', 'sediment')]
        for pair in invalid_pairs:
            if all(p in self.constraints for p in pair):
                self.logger.warning('Constraints specified with invalid pair: {}'.format(pair))

        for loc, value in dict(self.constraints).items():
            self.constrain(loc, value)

    def create(self, value, unit = None, hasOld = False, **kwargs):
        """
        Create a :class:`~fipy.Variable` on the domain.

        Args:
            value (int, float, array, PhysicalField): the value for the array
            unit (str): physical units string for the variable. Is overridden if `value` is a
            `PhysicalField`.
            hasOld (bool): flag to indicate how variable values are updated

        Returns:
            instance of the variable created

        Raises:
            RuntimeError: if a domain variable with `name` already exists, or no mesh exists on
            the domain.
            ValueError: if value.shape is not 1 or the domain shape

        """
        self.logger.debug('Creating variable {!r} with unit {}'.format(self.name, unit))

        self.var = self.domain.create_var(name=self.name, value=value, unit=unit, hasOld=hasOld,
                                          **kwargs)

        return self.var

    def constrain(self, loc, value):
        """
        Constrain the variable at the given location to the given value

        Args:
            loc (str): One of `("top", "bottom", "dbl", "sediment")
            value (numeric): a numeric value for the constraint, such as a number of a
            `PhysicalField`

        Returns:
            None

        Raises:
            ValueError for improper values for `loc`
            ValueError if value is not a 0-dimension array
            RuntimeError if variable doesn't exist

        """
        if self.var is None:
            raise RuntimeError('Variable {} does not exist!'.format(self.name))

        self.logger.debug("Setting constraint for {!r}: {} = {}".format(self.var, loc, value))

        if loc in ('top', 'bottom'):
            mask = self._LOCs[loc]

        else:
            mask = numerix.zeros(self.var.shape, dtype=bool)

            try:
                L = self._LOCs[loc]
                self.logger.debug('Constraint mask loc: {}'.format(L))
                mask[L] = 1
            except KeyError:
                raise ValueError('loc={} not in {}'.format(loc, tuple(self._LOCs.keys())))

        if isinstance(value, PhysicalField):
            value = value.inUnitsOf(self.var.unit)
        else:
            value = PhysicalField(value, self.var.unit)

        self.logger.info('Constraining {!r} at {} = {}'.format(self.var, loc, value))

        self.var.constrain(value, mask)

    def seed(self, profile, **kwargs):
        """
        Seed the value of the variable based on the profile and parameters

        Args:
            profile (str): The type of profile to use
            **kwargs: Parmeters for the profile

        Returns:
            None
        """
        PROFILES = ('linear', 'normal')

        if profile not in PROFILES:
            raise ValueError('Unknown profile {!r} not in {}'.format(profile, PROFILES))

        if profile == 'normal':
            from scipy.stats import norm
            loc = kwargs['loc']
            scale = kwargs['scale']
            coeff = kwargs['coeff']

            C = 1.0 / numerix.sqrt(2 * numerix.pi)

            # loc and scale should be in units of the domain mesh
            if hasattr(loc, 'unit'):
                loc_ = loc.inUnitsOf(self.domain.depths.unit).value
            else:
                loc_ = loc

            if hasattr(scale, 'unit'):
                scale_ = scale.inUnitsOf(self.domain.depths.unit).value
            else:
                scale_ = scale

            if hasattr(coeff, 'unit'):
                # check if compatible with variable unit
                try:
                    c = coeff.inUnitsOf(self.var.unit)
                except TypeError:
                    self.logger.error('Coeff {!r} not compatible with variable unit {!r}'.format(coeff, self.var.unit.name()))
                    raise ValueError('Incompatible unit of coefficient')

            self.logger.info('Seeding with profile normal loc: {} scale: {} coeff: {}'.format(loc_, scale_, coeff))

            normrv = norm(loc=loc_, scale=C**2*scale_)
            val = coeff * normrv.pdf(self.domain.depths) * C * scale_

            self.var.value = val

        elif profile == 'linear':
            start = kwargs['start']
            stop = kwargs['stop']
            N = self.var.shape[0]

            if hasattr(start, 'unit'):
                start_ = start.inUnitsOf(self.var.unit).value
            else:
                start_ = start

            if hasattr(stop, 'unit'):
                stop_ = stop.inUnitsOf(self.var.unit).value
            else:
                stop_ = stop

            self.logger.info('Seeding with profile linear: start: {} stop: {}'.format(start_, stop_))

            val = numerix.linspace(start_, stop_, N)
            self.var.value = val

        self.logger.debug('Seeded {!r} with {} profile'.format(self, profile))

    def snapshot(self, base = False):
        """
        Returns a snapshot of the variable's state

        Args:
            base (bool): Convert to base units?

        Returns:
            Dictionary with keys:
            * `data`: (numeric array, dict(unit))
            *`metadata`: dict with variable info: constraints
        """
        self.logger.debug('Snapshot: {}'.format(self))

        self.check_domain()

        state = dict()

        state['data'] = snapshot_var(self.var, base=base)

        meta = state['metadata'] = {}
        for cloc, cval in self.constraints.items():
            key = 'constraint_{}'.format(cloc)
            meta[key] = str(cval)

        return state