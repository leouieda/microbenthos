import logging
from collections import Mapping, Sequence, OrderedDict

import operator
from fipy.tools import numerix
from microbenthos.base import Entity
from sympy import sympify, symbols, lambdify, Symbol, SympifyError, Expr
from abc import ABCMeta, abstractmethod


class Process(Entity):
    """
    Class to represent a process occurring in the benthic domain.
    """

    __metaclass__ = ABCMeta

    def __init__(self, **kwargs):
        self.logger = kwargs.get('logger') or logging.getLogger(__name__)
        self.logger.debug('Init in Process')
        kwargs['logger'] = self.logger
        super(Process, self).__init__(**kwargs)

    @abstractmethod
    def dependent_vars(self):
        raise NotImplementedError

    @abstractmethod
    def add_response(self):
        pass

    @abstractmethod
    def evaluate(self, D, P=None, full=True):
        pass


class ExprProcess(Process):
    """
    Class to represent a process occurring in the benthic domain. This class helps to formulate
    an expression of the relationships between variables as well as update specific features with
    the simulation clocktime.
    """

    _lambdify_modules = (numerix, 'numpy')
    _sympy_ns = {}

    def __init__(self, formula, varnames, params = None, responses = None,
                 **kwargs):
        """
        Create a process expressed by the formula, possibly containing subprocesses.

        The scheme of operation involves converting the formula into a symbolic expression (
        using :meth:`sympify`), and symbols for the variables are created from `varnames`. This
        expression, stored in :attr:`expr`, is split into a core expression that is independent
        of the symbols indicating the subprocess. This core expression can be evaluated to
        perform computations by replacement by appropriate values during the evaulation phase.
        This core expression is made into a lambda function, and the expression is rendered into
        a callable function using :meth:`lambdify`. For computation in the model domain,
        the symbols are replaced by domain variables of the same name and parameters from the
        supplied `params` mapping. Any symbols referring to  subprocesses are replaced by the
        result of calling :meth:`.evaluate` on those instances.

        Args:
            formula (str): Valid expression for formula to be used with :meth:`sympify`
            varsnames (list): Names of the variables in the formula
            params (dict): Names and values for parameters in the formula. The names matching the
            symbols in the formula will be replaced during evaluation.
            responses: A mapping of {`name`: `params`} for any subprocesses of this process. The
            `params` must be a dict of the init arguments, for the same class.
            sympy_ns: A namespace dict for sympification (see: :meth:`sympify` arg `locals`)
            **kwargs: passed to superclass
        """
        super(ExprProcess, self).__init__(**kwargs)

        self._formula = None
        self.responses = OrderedDict()
        #: mapping of process name (str) to an instance of the Process

        if params is None:
            params = {}
        if not isinstance(params, Mapping):
            self.logger.warning('Params is not a Mapping, but {}'.format(type(params)))

        # self.params = OrderedDict((symbols(str(k)), v) for (k, v) in params.iteritems())
        # self.params_tuple = tuple(self.params)
        params = OrderedDict(params)
        self.check_names(params)
        self.params = params
        self.logger.debug('Stored params: {}'.format(self.params))

        self.check_names(varnames)
        self.varnames = tuple(varnames)
        self.vars = tuple(symbols([str(_) for _ in self.varnames]))
        self.logger.debug('Created var symbols: {}'.format(self.vars))

        self._formula = formula

        expr = self.parse_formula(formula)
        assert isinstance(expr, Expr)
        self.expr = expr
        # self.expr_core, self.expr_rest = self.split_core_expr(self.expr, self.args)

        responses = responses or {}
        self.check_names(responses)
        for k, v in responses.iteritems():
            self.add_response(k, **v)

        argsyms = [sympify(_) for _ in self.argnames]
        self.expr_func = self._lambdify(self.expr, argsyms)

    def __repr__(self):
        return 'Expr({},{})'.format(self.expr, self.vars)

    def check_names(self, p):
        improper = []
        for n in p:
            try:
                n_ = sympify(n)
            except:
                self.logger.warning('Name {} not valid expr'.format(n))
                improper.append(n)
        if improper:
            self.logger.error('Names are improper: {}'.format(improper))
            raise ValueError('Improper names found: {}'.format(improper))

    def dependent_vars(self):
        """

        Returns:
            List of variable names that this process (& its subprocesses) depend on

        """
        vars = []
        vars.extend(self.varnames)
        for proc in self.responses.values():
            vars.extend(proc.dependent_vars())
        return set(vars)

    @property
    def formula(self):
        return self._formula

    @property
    def argnames(self):
        return self.varnames + tuple(self.params)

    def parse_formula(self, formula):
        """
        Convert formula into an expression, also populating the responses

        Args:
            formula (str): formula as a string

        Returns:
            Instance of :class:`Expr`

        Raises:
            ValueError if :meth:`sympify` raises an exception
        """
        self.logger.debug('Parsing formula: {formula}'.format(formula=formula))
        self.logger.debug('Sympy namespace: {}'.format(self._sympy_ns))
        try:
            expr = sympify(formula, locals=self._sympy_ns)
            self.logger.info('Created expression: {}'.format(expr))

        except (SympifyError, SyntaxError):
            self.logger.error('Sympify failed on {}'.format(formula), exc_info=True)
            raise ValueError('Could not parse formula')

        return expr

    # def split_core_expr(self, expr, args):
    #     """
    #     Splits the given expression into a 'core' expr of its parameters and variables,
    #     and the rest of the subexpressions.
    #
    #     Args:
    #         expr: expr to split
    #
    #     Returns:
    #         Tuple of (core_expr, subexprs)
    #     """
    #     self.logger.debug('Splitting expr {} in terms of {}'.format(expr, args))
    #     rest, core_expr = expr.as_independent(*args)
    #     self.logger.debug('Core expr: {} & remaining: {}'.format(core_expr, rest))
    #     return core_expr, rest

    def add_response(self, name, **params):
        self.logger.debug('Adding response: {}:: {}'.format(name, params))

        response = self.from_dict(params)

        if name in self.responses:
            self.logger.warning('Process {!r} already exists. Over-writing with {}'.format(name,
                                                                                           response))
        self.responses[name] = response
        self.logger.info('Added response {!r}: {}'.format(name, response))

    def _lambdify(self, expr, args):
        """
        Make a lambda function from the expression

        Using :meth:`lambdify`, an :attr:`.exprfunc` function is created, which can be called
        with :attr:`.exprfunc_vars` as `exprfunc(*exprfunc_vars)` to evaluate the expression.
        `exprfunc_vars` also provides the order in which other arrays should be used to replace
        the symbols therein.

        Args:
            expr: if None, then :attr:`self.expr` is used

        Returns:
            exprfunc (lambda): a callable lambda function
            exprfunc_vars (tuple): the order of arguments (as symbols) to call the function with.

        """
        if not expr:
            raise ValueError('No expression to lambdify!')

        eatoms = {_ for _ in expr.atoms() if isinstance(_, Symbol)}
        # a set of the atoms (symbols) in the expr
        # we extract only symbols, and ignore the numbers

        # check that the expression actually only contains these symbols
        mismatched = set(args).difference(eatoms)
        if mismatched:
            self.logger.error(
                'Expression atoms {} mismatch with vars & params {}'.format(eatoms, args))
            raise ValueError('Expression & var/params mismatch!')

        self.logger.debug('Lambdifying: {} with args {}'.format(expr, args))
        exprfunc = lambdify(args, expr, modules=self._lambdify_modules)
        self.logger.debug('Created exprfunc: {} with args: {}'.format(exprfunc, args))

        return exprfunc

    # def get_source_term_for_var(self, varname, coeff = None):
    #     """
    #     Create a source term for solving domain computations
    #
    #     Args:
    #         varname: The name of the primary variable of the equation
    #         coeff: Any coefficient to be multiplied with the term
    #
    #     Returns:
    #         A Term or :class:`ImplicitSourceTerm`
    #
    #     """
    #     self.check_domain()
    #
    #     var_ = symbols(varname, seq=True)
    #     assert len(var_) == 1, 'Only one var should be supplied for source term'
    #     var = var_[0]
    #
    #     # collect variables from the domain
    #     tvars = tuple([self.domain[v.name] for v in self.exprfunc_vars])
    #     tparams = tuple(self.params[p] for p in self.exprfunc_params)
    #     targs = tvars + tparams
    #
    #     try:
    #         self.logger.debug('Creating term from args: {}'.format([(repr(_), type(_)) for _
    #                                                                 in targs]))
    #         term = self.exprfunc(*targs)
    #         self.logger.debug('Term created: {}'.format(repr(term)))
    #     except:
    #         self.logger.error('Term could not be created', exc_info=True)
    #         raise
    #
    #     if coeff is not None:
    #         term *= coeff
    #         self.logger.debug('Term with coeff: {}'.format(repr(term)))
    #
    #     other_vars = set(self.vars).difference({var})
    #
    #     if other_vars:
    #         # there are other variables in the expression, so it must be an implicit source term
    #         self.logger.debug(
    #             'Rendering as implicit source due to dependence on {}'.format(other_vars))
    #         return ImplicitSourceTerm(coeff=term, var=self.domain[var.name])
    #
    #     else:
    #         return term

    def evaluate(self, D, P = None, full=True):

        if P is None:
            P = {}

        # collect the arguments
        varargs = [D[_] for _ in self.varnames]
        if not P:
            P = self.params
        pargs = [P[_] for _ in self.params]
        args = varargs + pargs
        # follow the same order of the params ordered dict

        self.logger.debug('Evaluating {} with args: {}'.format(self.expr, args))
        evaled = self.expr_func(*args)

        resp_evals = []
        if full:
            # evaluate the subprocesses
            for resp_name, response in self.responses.items():
                self.logger.debug('Evaluating response {}'.format(resp_name))
                resp_evals.append(response.evaluate(D, P.get(resp_name, None)))

        if resp_evals:
            return evaled * reduce(operator.mul, resp_evals)
        else:
            return evaled
