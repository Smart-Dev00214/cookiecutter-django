from exceptions import Exception

from django.conf import settings

class AppNotFoundError(Exception):
    pass

def import_module(mod_name, classes=[]):
    """
    For dynamically importing classes from a module based on the mapping within 
    settings.py
    
    Eg. calling import_module('product.models') will search INSTALLED_APPS for
    the relevant product app (default is 'oscar.product') and then import the
    classes from there.   
    
    We search the INSTALLED_APPS list to find the appropriate app string and 
    import that.
    """
    # Classes must be specified in order for __import__ to work correctly.  It's
    # also a good practice
    if not classes:
        raise ValueError("You must specify the classes to import")
    # Arguments will be things like 'product.models' and so we
    # we take the first component to find within the INSTALLED_APPS list.
    app_name = mod_name.split(".")[0]
    for installed_app in  settings.INSTALLED_APPS:
        # We search the second component of the installed apps
        installed_app_parts = installed_app.split(".")
        try: 
            if app_name == installed_app_parts[1]:
                real_app = "%s.%s" % (installed_app_parts[0], mod_name)
                return __import__(real_app, fromlist=classes)
        except IndexError:
            pass
    raise AppNotFoundError("Unable to find an app matching %s in INSTALLED_APPS" % (app_name,))
    