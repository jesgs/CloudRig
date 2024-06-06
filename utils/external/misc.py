import typing
from rna_prop_ui import rna_idprop_value_to_python

T = typing.TypeVar('T')
Lazy: typing.TypeAlias = T | typing.Callable[[], T]
OptionalLazy: typing.TypeAlias = typing.Optional[T | typing.Callable[[], T]]


def force_lazy(value: OptionalLazy[T]) -> T:
    """If the argument is callable, invokes it without arguments.
    Otherwise, returns the argument as is."""
    if callable(value):
        return value()
    else:
        return value


def property_to_python(value) -> typing.Any:
    value = rna_idprop_value_to_python(value)

    if isinstance(value, dict):
        return {k: property_to_python(v) for k, v in value.items()}
    elif isinstance(value, list):
        return map_list(property_to_python, value)
    else:
        return value


def map_list(func, *inputs):
    """[func(a0,b0...), func(a1,b1...), ...]"""
    return list(map(func, *inputs))
