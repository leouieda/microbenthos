import importlib
import inspect
import logging

from microbenthos.domain import SedimentDBLDomain


class Entity(object):

    def __init__(self, logger = None):

        if not logger:
            self.logger = logging.getLogger(__name__)
            self.logger.warning('No logger supplied, creating in base class: {}'.format(__name__))
        else:
            self.logger = logger


    @classmethod
    def from_params(cls, cls_path, init_params, post_params=None):
        """
        Create entity instance from supplied CLS path and init parameters

        CLS is a string such as `Irradiance` or `microbenthos.Process` or `sympy.Lambda`

        Args:
            cls_path (str): The qualified `module.class_name`. If no `module` is in the string,
            then it is assummed to be `"microbenthos"`

            init_params (dict): Dictionary of params to supply to the class __init__

            post_params (dict): Dictionary of params for :meth:`post_init` if available

        Returns:
            Instance of the entity

        """
        logger = logging.getLogger(__name__)
        logger.debug('Setting up entity from cls_path: {}'.format(cls_path))
        try:
            cls_modname, cls_name = cls_path.rsplit('.', 1)
        except ValueError:
            # raise ValueError('Path {} could not be split into module & class'.format(cls_path))
            # this is then just a class name to import from microbenthos
            cls_modname = 'microbenthos'
            cls_name = cls_path

        try:
            logger.debug('Importing {}'.format(cls_modname))
            cls_module = importlib.import_module(cls_modname)
            CLS = getattr(cls_module, cls_name)
            logger.debug('Using class: {}'.format(CLS))
        except (ImportError, AttributeError):
            raise TypeError('Class {} in {} could not be found!'.format(cls_modname, cls_name))

        logger.debug('Init params: {}'.format(init_params))
        inst = CLS(**init_params)

        post_params = post_params or {}

        if hasattr(inst, 'post_init'):
            logger.debug("Calling post_init for instance: {}".format(post_params))
            inst.post_init(**post_params)

        logger.info('Created entity: {}'.format(inst))
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

        return cls.from_params(cls_path=cls_path, init_params=init_params, post_params=post_params)

    def post_init(self, **kwargs):
        """
        Hook to customize initialization of entity after construction by :meth:`.from_dict`. This
        must be overriden by subclasses, to be useful.

        Args:
            **kwargs:

        Returns:
            None
        """
        self.logger.debug('Empty post_init on {}'.format(self))


class DomainEntity(Entity):
    """
    A base class that represents entities in the microbenthic environment. This can be used to
    subclass microbial groups, chemical reactions, or other parameters. The class provides a
    uniform interface to add the entity to the simulation domain and setup parameters and update
    according to the simulation clock.
    """

    def __init__(self, domain_cls = SedimentDBLDomain, **kwargs):

        super(DomainEntity, self).__init__(**kwargs)

        assert inspect.isclass(domain_cls), 'domain_cls should be a class! Got {}'.format(
            type(domain_cls)
            )
        self.domain_cls = domain_cls

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

        if not isinstance(domain, self.domain_cls):
            self.logger.warning('Domain must be an instance of {}, not {}'.format(
                self.domain_cls.__name__, type(domain)))
        # raise TypeError('Wrong domain type received!')

        self._domain = domain
        self.logger.info('Added to domain: {}'.format(self))

    def set_domain(self, domain):
        self.domain = domain

    def check_domain(self):
        if self.domain is None:
            raise RuntimeError('Domain required for setup')
        return self.has_domain

    @property
    def has_domain(self):
        return isinstance(self.domain, self.domain_cls)

    def setup(self):
        """
        Method to set up the mat entity once a domain is available

        This may include logic to add any featuers it has also to the domain.

        To be overridden by subclasses
        """
        self.logger.debug('Setup: {}'.format(self))
        raise NotImplementedError('Setup of {}'.format(self.__class__.__name__))

    def update_time(self, clocktime):
        """
        Method which should update the entity features for the simulation clocktime

        :param float clocktime: The simulation time (units depends on the solver setup)
        """
        self.logger.debug('Updating {} for clocktime {}'.format(self, clocktime))


