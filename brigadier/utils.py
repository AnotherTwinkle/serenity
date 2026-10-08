import inspect

def safeget(l, i, d = None):
    try:
        return l[i]
    except IndexError:
        return d

def safegetrange(l, i, ds = []):
    x = 0
    r = []
    for j in range(i):
        try:
            r.append(l[j])
        except IndexError:
            r.append(ds[x])
            x += 1
    return r

def getattr(obj, target, default= None):
    try:
        return obj.__getattribute__(target)
    except AttributeError:
        return default

def get_default_args(func):
    signature = inspect.signature(func)
    return {
        k: v.default
        for k, v in signature.parameters.items()
        if v.default is not inspect.Parameter.empty
    }

def get_annotated_args(func):
    signature = inspect.signature(func)
    return {
        k : v.annotation
        for k, v in signature.parameters.items()
        if v.annotation is not inspect.Parameter.empty
    }

class MISSING:
    """The default `type` value for flags"""
    pass