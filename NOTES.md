### Customisations

```python
# following was added to python clang bindings in SourceLocation class
def is_in_system_header(self):
    """Get the file offset represented by this source location."""
    return conf.lib.clang_Location_isInSystemHeader(self)
```
