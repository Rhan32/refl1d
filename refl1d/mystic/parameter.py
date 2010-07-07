# This program is public domain
# Author: Paul Kienzle
__all__ = [ 'Parameter', 'ParameterSet']

import sys
import numpy

from . import bounds as mbounds
from .formatnum import format_uncertainty

# TODO: avoid evaluation of subexpressions if parameters do not change.
# This is especially important if the subexpression invokes an expensive
# calculation via a parameterized function.  This will require a restructuring
# of the parameter class.  The park-1.3 solution is viable: given a parameter
# set, figure out which order the expressions need to be evaluated by
# building up a dependency graph.  With a little care, we can check which
# parameters have actually changed since the last calculation update, and
# restrict the dependency graph to just them.
# TODO: support full aliasing, so that floating point model attributes can
# be aliased to a parameter.  The same technique as subexpressions applies:
# when the parameter is changed, the model will be updated and will need
# to be re-evaluated.


class BaseParameter(object):

    # Parameters are fixed unless told otherwise
    fixed = True
    fittable = False
    discrete = False
    bounds = mbounds.Unbounded()

    # Parameters may be dependent on other parameters, and the
    # fit engine will need to access them.
    def parameters(self):
        return [self]

    def pmp(self, *args):
        """
        Allow the parameter to vary as value +/- percent.

        pmp(percent) -> [value*(100 - percent)/100, value*(100 + percent)/100]
        pmp(plus,minus) -> [value*(100 - minus)/100, value*(100 + plus)/100]

        This uses nice numbers for the resulting range.
        """
        if self.fittable: self.fixed = False
        self.bounds = mbounds.Bounded(*mbounds.pmp(self.value, *args))
        return self
    def pm(self, *args):
        """
        Allow the parameter to vary as value +/- delta.

        pm(delta) -> [value-delta, value+delta]
        pm(plus,minus) -> [value-minus, value+plus]

        This uses nice numbers for the resulting range.
        """
        if self.fittable: self.fixed = False
        self.bounds = mbounds.Bounded(*mbounds.pm(self.value, *args))
        return self
    def dev(self, std=1):
        """
        Allow the parameter to vary according to a normal distribution, with
        deviations added to the overall cost function.

        dev(sigma) -> Normal(mean=value,std=sigma)
        """
        if self.fittable: self.fixed = False
        self.bounds = mbounds.Normal(self.value,std)
        return self
    def range(self, low, high):
        """
        Allow the parameter to vary within the given range.
        """
        if self.fittable: self.fixed = False
        self.bounds = mbounds.Bounded(low,high)
        return self

    # Functional form of parameter value access
    def __call__(self): return self.value

    # Parameter algebra: express relationships between parameters
    def __gt__(self, other): return ConstraintGT(self, other)
    def __ge__(self, other): return ConstraintGE(self, other)
    def __le__(self, other): return ConstraintLE(self, other)
    def __lt__(self, other): return ConstraintLT(self, other)
    ## Don't deal with equality constraints yet
    #def __eq__(self, other): return ConstraintEQ(self, other)
    #def __ne__(self, other): return ConstraintNE(self, other)
    def __add__(self, other): return OperatorAdd(self,other)
    def __sub__(self, other): return OperatorSub(self,other)
    def __mul__(self, other): return OperatorMul(self,other)
    def __div__(self, other): return OperatorDiv(self,other)
    def __pow__(self, other): return OperatorPow(self,other)
    def __radd__(self, other): return OperatorAdd(other,self)
    def __rsub__(self, other): return OperatorSub(other,self)
    def __rmul__(self, other): return OperatorMul(other,self)
    def __rdiv__(self, other): return OperatorDiv(other,self)
    def __rpow__(self, other): return OperatorPow(other,self)
    def __abs__(self): return _abs(self)
    def __neg__(self): return _mul(self,-1)
    def __pos__(self): return self
    def __float__(self): return float(self.value)

class Parameter(BaseParameter):
    """
    A parameter is a symbolic value.

    It can be fixed or it can vary within bounds.

    p = Parameter(3).pmp(10)    # 3 +/- 10%
    p = Parameter(3).pmp(-5,10) # 3 in [2.85,3.3] rounded to 2 digits
    p = Parameter(3).pm(2)      # 3 +/- 2
    p = Parameter(3).pm(-1,2)   # 3 in [2,5]
    p = Parameter(3).range(0,5) # 3 in [0,5]

    It has hard limits on the possible values, and a range that should live
    within those hard limits.  The value should lie within the range for
    it to be valid.  Some algorithms may drive the value outside the range
    in order to satisfy soft It has a value which should lie within the range.

    Other properties can decorate the parameter, such as tip for tool tip
    and units for units.
    """
    fittable = True
    @classmethod
    def default(cls, value, **kw):
        # Need to constrain the parameter to fit within fixed limits and
        # to receive a name if a name has not already been provided.
        if isinstance(value, BaseParameter):
            return value
        else:
            return cls(value, **kw)
    def set(self, value):
        self.value = value
    def __init__(self, value=None, bounds=None, fixed=None, name=None, **kw):
        # UI nicities:
        # 1. check if we are started with value=range or bounds=range; if we are given bounds, then assume
        # this is a fittable parameter, otherwise the parameter
        # defaults to fixed; if value is not set, use the midpoint
        # of the range.
        if bounds is not None:
            try:
                lo, hi = value
                bounds = lo, hi
                value = None
            except TypeError:
                pass
        if fixed is None:
            fixed = (bounds is None)
        bounds = mbounds.init_bounds(bounds)
        if value is None:
            value = bounds.start_value()

        # Store whatever values the user needs to associate with the parameter
        # Models should set units and tool tips so the user interface has
        # something to work with.
        for k,v in kw.items():
            setattr(self,k,v)

        # The real initialization
        self.bounds = bounds
        self.value = value
        self.fixed = fixed
        self.name = name

    def feasible(self):
        """
        Value is within the limits defined by the model
        """
        self.limits[0] <= self.value <= self.limits[1]

    def rand(self, rng=mbounds.RNG):
        """
        Set a random value for the parameter.
        """
        self.value = self.bounds.rand(rng)

    def nllf(self):
        """
        Return the negative log likelihood of seeing the current parameter value.
        """
        return self.bounds.nllf(self.value)

    def residual(self):
        """
        Return the negative log likelihood of seeing the current parameter value.
        """
        return self.bounds.residual(self.value)

    def valid(self):
        return not numpy.isinf(self.nllf())

    def format(self):
        return "%s=%g in %s"%(self,self.value,self.bounds)

    def __str__(self):
        name = self.name if self.name != None else '?'
        return name

    def __repr__(self):
        return "Parameter(%s)"%self

class Reference(Parameter):
    """
    Create an adaptor so that a model attribute can be treated as if it
    were a parameter.  This allows only direct access, wherein the
    storage for the parameter value is provided by the underlying model.
    
    Indirect access, wherein the storage is provided by the parameter, cannot 
    be supported since the parameter has no way to detect that the model 
    is asking for the value of the attribute.  This means that model 
    attributes cannot be assigned to parameter expressions without some
    trigger to update the values of the attributes in the model.
    """
    def __init__(self, obj, attr, name=None):
        self.obj = obj
        self.attr = attr
        if name is not None:
            self.name = name
        else:
            self.name = ".".join([obj.__class__.__name__, attr])
    def _getvalue(self):
        return getattr(self.obj, self.attr)
    def _setvalue(self, value):
        setattr(self.obj, self.attr, value)
    value = property(_getvalue, _setvalue)

# Current implementation computes values on the fly, so you only
# need to plug the values into the parameters and the parameters
# are automatically updated.
#
# This will not work well for wrapped models.  In those cases you
# want to do a number of optimizations, such as only updating the
#

# ==== Comparison operators ===
class Constraint:
    """
    Abstract base class for constraints.
    """
    def __bool__(self):
        """
        Returns True if the condition is satisfied
        """
        raise NotImplementedError
    __nonzero__ = __bool__
    def __str__(self):
        """
        Text description of the constraint
        """
        raise NotImplementedError

def _gen_constraint(name,op):
    """
    Generate a comparison function from a comparison operator.
    """
    return '''\
class Constraint%(name)s(Constraint):
    """
    Constraint operator %(op)s
    """
    def __init__(self, a, b):
        self.a, self.b = a,b
    def __bool__(self):
        return float(self.a) %(op)s float(self.b)
    __nonzero__ = __bool__
    def __str__(self):
        return "(%%s %(op)s %%s)"%%(self.a,self.b)
'''%dict(name=name,op=op)

exec _gen_constraint('GT','>')
exec _gen_constraint('GE','>=')
exec _gen_constraint('LE','<=')
exec _gen_constraint('LT','<')
exec _gen_constraint('EQ','==')
exec _gen_constraint('NE','!=')


# ==== Arithmetic operators ===
def _gen_binop(name,op):
    """
    Generate a comparison function from a comparison operator.
    """
    return '''\
class Operator%(name)s(BaseParameter):
    """
    Parameter operator %(op)s
    """
    def __init__(self, a, b):
        self.a, self.b = a,b
        pars = []
        if isinstance(a,BaseParameter): pars += a.parameters()
        if isinstance(b,BaseParameter): pars += b.parameters()
        self._parameters = pars
    def parameters(self):
        return self._parameters
    def _value(self):
        return float(self.a) %(op)s float(self.b)
    value = property(_value)
    def _dvalue(self):
        return float(self.a)
    dvalue = property(_dvalue)
    def __str__(self):
        return "(%%s %(op)s %%s)"%%(self.a,self.b)
'''%dict(name=name,op=op)

exec _gen_binop('Add','+')
exec _gen_binop('Sub','-')
exec _gen_binop('Mul','*')
exec _gen_binop('Div','/')
exec _gen_binop('Pow','**')


def substitute(a):
    """
    Return structure a with values substituted for all parameters.

    The function traverses lists, tuples and dicts recursively.  Things
    which are not parameters are returned directly.
    """
    if isinstance(a, BaseParameter):
        return float(a.value)
    elif isinstance(a, tuple):
        return tuple(substitute(v) for v in a)
    elif isinstance(a, list):
        return [substitute(v) for v in a]
    elif isinstance(a, dict):
        return dict((k,substitute(v)) for k,v in a.items())
    else:
        return a

class Function(BaseParameter):
    """
    Delayed function evaluator.

    f.value evaluates the function with the values of the
    parameter arguments at the time f.value is referenced rather
    than when the function was invoked.
    """
    __slots__ = ['op','args','kw']
    def __init__(self, op, *args, **kw):
        self.op,self.args,self.kw = op,args,kw
    def parameters(self):
        # Figure out which arguments to the function are parameters
        #deps = [p for p in self.args if isinstance(p,BaseParameter)]
        deps = flatten((self.args,self.kw))
        # Find out which other parameters these parameters depend on.
        res = []
        for p in deps: res.extend(p.parameters())
        return res
    def _value(self):
        # Expand args and kw, replacing instances of parameters
        # with their values
        #return self.op(*[float(v) for v in self.args], **self.kw)
        return self.op(*substitute(self.args), **substitute(self.kw))
    value = property(_value)
    def __str__(self):
        args = [str(v) for v in self.args]
        kw = [str(k)+"="+str(v) for k,v in self.kw.items()]
        return self.op.__name__ + "(" + ", ".join(args+kw) + ")"
from functools import wraps
def function(op):
    """
    Convert a function into a delayed evaluator.

    The value of the function is computed from the values of the parameters
    at the time that the function value is requested rather than when the
    function is created.
    """
    # Note: @functools.wraps(op) does not work with numpy ufuncs
    # Note: @decorator does not work with builtins like abs
    def function_generator(*args, **kw):
        return Function(op, *args, **kw)
    function_generator.__name__ = op.__name__
    function_generator.__doc__ = op.__doc__
    return function_generator
_abs = function(abs)



def flatten(s):
    if isinstance(s, (tuple,list)):
        return reduce(lambda a,b: a + flatten(b), s, [])
    elif isinstance(s, set):
        raise TypeError("parameter flattening cannot order sets")
    elif isinstance(s, dict):
        return reduce(lambda a,b: a + flatten(s[b]), sorted(s.keys()), [])
    elif isinstance(s, BaseParameter):
        return [s]
    elif s is None:
        return []
    else:
        raise TypeError("don't understand type "+str(type(s)))

def format(p, indent=0):
    """
    Format parameter set for printing.

    Note that this only says how the parameters are arranged, not how they
    relate to each other.
    """
    if isinstance(p,dict) and p != {}:
        res = []
        for k in sorted(p.keys()):
            s = format(p[k], indent+2)
            label = " "*indent+"."+k
            if s.endswith('\n'):
                res.append(label+"\n"+s)
            else:
                res.append(label+" = "+s+'\n')
        return "".join(res)
    elif isinstance(p, list) and p != []:
        res = []
        for k,v in enumerate(p):
            s = format(v, indent+2)
            label = " "*indent+"[%d]"%k
            if s.endswith('\n'):
                res.append(label+'\n'+s)
            else:
                res.append(label+' = '+s+'\n')
        return "".join(res)
    elif isinstance(p, Parameter):
        if p.fixed:
            bounds = ""
        else:
            bounds=", bounds=(%g,%g)"%(p.bounds.limits[0],p.bounds.limits[1])
        return "Parameter(%g, name='%s'%s)"%(p.value,str(p),bounds)
    elif isinstance(p, BaseParameter):
        return str(p)
    else:
        return "None"

def summarize(pars, fid=None):
    """
    Print a stylized list of parameter names and values with range bars.
    """
    if fid is None: fid = sys.stdout
    for p in sorted(pars, cmp=lambda x,y: cmp(x.name,y.name)):
        if not numpy.isfinite(p.value):
            bar = "*invalid* "
        else:
            position = int(p.bounds.get01(p.value)*9.999999999)
            bar = ['.']*10
            if position < 0: bar[0] = '<'
            elif position > 9: bar[9] = '>'
            else: bar[position] = '|'
        print >>fid, "%40s %s %10g in %s"%(p.name,"".join(bar),p.value,p.bounds)

def unique(s):
    """
    Return the unique set of parameters
    
    The ordering is stable.  The same parameters/dependencies will always
    return the same ordering, with the first occurrence first.
    """
    # Walk structures such as dicts and lists
    pars = flatten(s)
    # Also walk parameter expressions
    pars = pars + flatten([p.parameters() for p in pars])

    # TODO: implement n log n rather than n^2 uniqueness algorithm
    # Should be able to do it with a stable sort of ids, and keeping
    # the first id of each run.
    result = []
    for p in pars:
        if p not in result:
            result.append(p)
    # Return the complete set of parameters    
    return result

def fittable(s):
    """
    Return the list of fittable parameters in no paraticular order.

    Note that some fittable parameters may be fixed during the fit.
    """
    return [p for p in unique(s) if not p.fittable]

def varying(s):
    """
    Return the list of fitted parameters in the model.

    This is the set of parameters that will vary during the fit.
    """

    return [p for p in unique(s) if not p.fixed]

def randomize(s):
    """
    Set random values to the parameters in the parameter set, with
    values chosen according to the bounds.
    """
    for p in s: p.value = p.bounds.random(1)[0]

def current(s):
    return [p.value for p in s]

# ========= trash ===================

class ParameterSet:
    def __init__(self, **kw):
        self.__dict__ = kw
    def flatten(self, prefix=""):
        L = []
        for k,v in self.__dict__:
            if isinstance(v, ParameterSet):
                L.extend(v.flatten(prefix=prefix+k+"."))
            elif isinstance(v, list):
                L.extend((prefix+k+"[%d]"%i,p) for i,p in enumerate(v))
            else:
                L.append((prefix+k,v))
        return L

class IntegerParameter(Parameter):
    discrete = True
    def rand(self, rng=mbounds.RNG):
        """
        Set a random value for the parameter.
        """
        self.value = numpy.floor(self.bounds.rand(rng))

    pass

class VectorParameter(Parameter):
    pass

class Alias(object):
    """
    Parameter alias.
    
    Rather than modifying a model to contain a parameter slot,
    allow the parameter to exist outside the model. The resulting
    parameter will have the full parameter semantics, including
    the ability to replace a fixed value with a parameter expression.
    """
    def __init__(self, obj, attr, p=None, name=None):
        self.obj = obj
        self.attr = attr
        if name is None:
            name = ".".join([obj.__class__.__name__, attr])
        self.p = Parameter.default(p, name=name)
    def update(self):
        setattr(self.obj,self.attr,self.par.value)
    def parameters(self):
        return self.p.parameters()

