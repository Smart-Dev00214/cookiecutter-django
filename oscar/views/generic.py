from django import forms
from django.core import validators
from django.core.exceptions import ValidationError
from django.utils.encoding import smart_str
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.utils.translation import ugettext_lazy as _

import phonenumbers
from oscar.core.phonenumber import PhoneNumber


class PostActionMixin(object):
    """
    Simple mixin to forward POST request that contain a key 'action'
    onto a method of form "do_{action}".

    This only works with DetailView
    """
    def post(self, request, *args, **kwargs):
        if 'action' in self.request.POST:
            model = self.get_object()
            # The do_* method is required to do what it needs to with the model
            # it is passed, and then to assign the HTTP response to
            # self.response.
            method_name = "do_%s" % self.request.POST['action'].lower()
            if hasattr(self, method_name):
                getattr(self, method_name)(model)
                return self.response
            else:
                messages.error(request, _("Invalid form submission"))
        return super(PostActionMixin, self).post(request, *args, **kwargs)


class BulkEditMixin(object):
    """
    Mixin for views that have a bulk editing facility.  This is normally in the
    form of tabular data where each row has a checkbox.  The UI allows a number
    of rows to be selected and then some 'action' to be performed on them.
    """
    action_param = 'action'

    # Permitted methods that can be used to act on the selected objects
    actions = None
    current_view = None
    checkbox_object_name = None

    def get_checkbox_object_name(self):
        if self.checkbox_object_name:
            return self.checkbox_object_name
        object_list = self.get_queryset()
        if hasattr(object_list, 'model'):
            return smart_str(object_list.model._meta.object_name.lower())
        else:
            return None

    def get_queryset(self):
        pass

    def get_error_url(self, request):
        return request.META.get('HTTP_REFERER', '.')

    def get_success_url(self, request):
        return request.META.get('HTTP_REFERER', '.')

    def post(self, request, *args, **kwargs):
        # Dynamic dispatch pattern - we forward POST requests onto a method
        # designated by the 'action' parameter.  The action has to be in a
        # whitelist to avoid security issues.
        action = request.POST.get(self.action_param, '').lower()
        if not self.actions or action not in self.actions:
            messages.error(self.request, _("Invalid action"))
            return HttpResponseRedirect(self.get_error_url(request))

        ids = request.POST.getlist(
            'selected_%s' % self.get_checkbox_object_name())
        ids = map(int, ids)
        if not ids:
            messages.error(
                self.request,
                _("You need to select some %ss") % self.get_checkbox_object_name())
            return HttpResponseRedirect(self.get_error_url(request))

        objects = self.get_objects(ids)
        return getattr(self, action)(request, objects)

    def get_objects(self, ids):
        object_dict = self.get_object_dict(ids)
        # Rearrange back into the original order
        return [object_dict[id] for id in ids]

    def get_object_dict(self, ids):
        return self.model.objects.in_bulk(ids)


class PhoneNumberMixin(object):
    """
    Validation mixin for forms with a phone number, and optionally a country.
    It tries to validate the phone number, and on failure tries to validate it
    using a hint (the country provided), and treating it as a local number.
    
    It looks for ``self.country``, or ``self.fields['country'].queryset``
    """
    
    phone_number = forms.CharField(max_length=32, required=False)

    def clean_phone_number(self):
        number = self.cleaned_data['phone_number']

        # empty
        if number in validators.EMPTY_VALUES:
            return None
        
        # Check for an international phone format
        try:
            phone_number = PhoneNumber.from_string(number)
        except phonenumbers.NumberParseException:
            # Try hinting with the shipping country
            if hasattr(self.instance, 'country'):
                country = self.instance.country
            elif hasattr(self.fields.get('country'), 'queryset'):
                country = self.fields['country'].queryset[0]
            else:
                country = None

            if country:
                country = self.cleaned_data.get('country', country)
                            
                region_code = country.iso_3166_1_a2
                # The PhoneNumber class does not allow specifying
                # the region. So we drop down to the underlying phonenumbers library,
                # which luckily allows parsing into a PhoneNumber instance
                try:
                    phone_number = PhoneNumber.from_string(number, region=region_code)
                    if not phone_number.is_valid():
                        raise ValidationError(
                            _(u'This is not a valid local phone format for %s.') % country)
                except phonenumbers.NumberParseException:
                    # Not a valid local or international phone number
                    raise ValidationError(
                        _(u'This is not a valid local or international phone format.'))
            else:
                # There is no shipping country, not a valid international number
                raise ValidationError(
                    _(u'This is not a valid international phone format.'))

        return phone_number
