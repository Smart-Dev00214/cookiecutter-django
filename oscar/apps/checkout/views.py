from decimal import Decimal
import logging

from django.conf import settings
from django.http import HttpResponse, Http404, HttpResponseRedirect, HttpResponseBadRequest
from django.template import RequestContext
from django.shortcuts import get_object_or_404
from django.core.urlresolvers import reverse
from django.forms import ModelForm
from django.contrib import messages
from django.core.urlresolvers import resolve
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import ugettext as _
from django.template.response import TemplateResponse
from django.core.mail import EmailMessage
from django.views.generic import DetailView, TemplateView, FormView, DeleteView, UpdateView, CreateView

from oscar.core.loading import import_module
import_module('checkout.forms', ['ShippingAddressForm'], locals())
import_module('checkout.calculators', ['OrderTotalCalculator'], locals())
import_module('checkout.utils', ['ProgressChecker', 'CheckoutSessionData'], locals())
import_module('checkout.signals', ['pre_payment', 'post_payment'], locals())
import_module('checkout.core_views', ['CheckoutView'], locals())
import_module('order.models', ['Order', 'ShippingAddress', 'CommunicationEventType', 'CommunicationEvent'], locals())
import_module('order.utils', ['OrderNumberGenerator', 'OrderCreator'], locals())
import_module('address.models', ['UserAddress'], locals())
import_module('address.forms', ['UserAddressForm'], locals())
import_module('shipping.repository', ['Repository'], locals())
import_module('customer.models', ['Email'], locals())
import_module('payment.exceptions', ['RedirectRequiredException', 'UnableToTakePaymentException', 
                                     'PaymentException'], locals())
import_module('basket.models', ['Basket'], locals())

# Standard logger for checkout events
logger = logging.getLogger('oscar.checkout')


class IndexView(TemplateView):
    """
    First page of the checkout.  If the user is signed in then we forward
    straight onto the next step.  Otherwise, we provide options to login, register and
    (if the option is enabled) proceed anonymously.
    """
    template_name = 'oscar/checkout/gateway.html'
    
    def get(self, request, *args, **kwargs):
        if self.request.user.is_authenticated():
            return HttpResponseRedirect(reverse('oscar-checkout-shipping-address'))
        return super(IndexView, self).get(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        return {'is_anon_checkout_allowed': getattr(settings, 'OSCAR_ALLOW_ANON_CHECKOUT', False)}


# ================
# SHIPPING ADDRESS
# ================


class ShippingAddressView(FormView):
    """
    Determine the shipping address for the order.
    
    The default behaviour is to display a list of addresses from the users's
    address book, from which the user can choose one to be their shipping address.
    They can add/edit/delete these USER addresses.  This address will be
    automatically converted into a SHIPPING address when the user checks out.
    
    Alternatively, the user can enter a SHIPPING address directly which will be
    saved in the session and saved as a model when the order is sucessfully submitted.
    """
    
    template_name = 'oscar/checkout/shipping_address.html'
    form_class = ShippingAddressForm
    
    def get_initial(self):
        co_data = CheckoutSessionData(self.request)
        return co_data.new_address_fields()
    
    def get_context_data(self, **kwargs):
        if self.request.user.is_authenticated():
            # Look up address book data
            kwargs['addresses'] = UserAddress._default_manager.filter(user=self.request.user)
        return kwargs
    
    def post(self, request, *args, **kwargs):
        # Check if a shipping address was selected directly (eg no form was filled in)
        if self.request.user.is_authenticated and 'address_id' in self.request.POST:
            address = UserAddress._default_manager.get(pk=self.request.POST['address_id'])
            if 'action' in self.request.POST and self.request.POST['action'] == 'ship_to':
                # User has selected a previous address to ship to
                co_data = CheckoutSessionData(self.request)
                co_data.ship_to_user_address(address)
                return self.get_success_response()
            elif 'action' in self.request.POST and self.request.POST['action'] == 'delete':
                address.delete()
                messages.info(self.request, "Address deleted from your address book")
                return HttpResponseRedirect(reverse('oscar-checkout-shipping-method'))
            else:
                return HttpResponseBadRequest()
        else:
            return super(ShippingAddressView, self).post(request, *args, **kwargs)
    
    def form_valid(self, form):
        co_data = CheckoutSessionData(self.request)
        co_data.ship_to_new_address(form.clean())
        return super(ShippingAddressView, self).form_valid(form)
    
    def get_success_response(self):
        return HttpResponseRedirect(reverse('oscar-checkout-shipping-method'))
    

class UserAddressCreateView(CreateView):
    """
    Add a USER address to the user's addressbook.

    This is not the same as creating a SHIPPING Address, although if used for the order,
    it will be converted into a shipping address at submission-time.
    """
    template_name = 'oscar/checkout/user_address_form.html'
    form_class = UserAddressForm

    def get_context_data(self, **kwargs):
        kwargs = super(UserAddressCreateView, self).get_context_data(**kwargs)
        kwargs['form_url'] = reverse('oscar-checkout-user-address-create')
        return kwargs
    
    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.user = self.request.user
        self.object.save()
        return self.get_success_response()

    def get_success_response(self):
        messages.info(self.request, _("Address saved"))
        # We redirect back to the shipping address page
        return HttpResponseRedirect(reverse('oscar-checkout-shipping-address'))
    
    
class UserAddressUpdateView(UpdateView):
    """
    Update a user address
    """
    template_name = 'oscar/checkout/user_address_form.html'
    form_class = UserAddressForm
    
    def get_queryset(self):
        return UserAddress._default_manager.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        kwargs = super(UserAddressUpdateView, self).get_context_data(**kwargs)
        kwargs['form_url'] = reverse('oscar-checkout-user-address-update', args=(str(kwargs['object'].id)))
        return kwargs

    def get_success_url(self):
        messages.info(self.request, _("Address saved"))
        return reverse('oscar-checkout-shipping-address')
    
    
class UserAddressDeleteView(DeleteView):
    """
    Delete an address from a user's addressbook.
    """

    def get_queryset(self):
        return UserAddress._default_manager.filter(user=self.request.user)
    
    def get_success_url(self):
        messages.info(self.request, _("Address deleted"))
        return reverse('oscar-checkout-shipping-address')
    

# ===============    
# Shipping method
# ===============    
    

class CheckoutSessionMixin(object):

    def get_shipping_address(self):
        # Load address data into a blank address model
        co_data = CheckoutSessionData(self.request)
        addr_data = co_data.new_address_fields()
        if addr_data:
            return ShippingAddress(**addr_data)
        addr_id = co_data.user_address_id()
        if addr_id:
            try:
                return UserAddress._default_manager.get(pk=addr_id)
            except UserAddress.DoesNotExist:
                # This can happen if you reset all your tables and you still have
                # session data that refers to addresses that no longer exist
                pass
        return None


class ShippingMethodView(TemplateView, CheckoutSessionMixin):
    """
    Shipping methods are domain-specific and so need implementing in a 
    subclass of this class.
    """
    template_name = 'oscar/checkout/shipping_methods.html';
    
    def get(self, request, *args, **kwargs):
        self._methods = self.get_available_shipping_methods()
        if len(self._methods) == 1:
            # Only one shipping method - set this and redirect onto the next step
            co_data = CheckoutSessionData(self.request)
            co_data.use_shipping_method(self._methods[0].code)
            return self.get_success_response()
        return super(ShippingMethodView, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs = super(ShippingMethodView, self).get_context_data(self, **kwargs)
        kwargs['methods'] = self._methods
        return kwargs

    def get_available_shipping_methods(self):
        """
        Returns all applicable shipping method objects
        for a given basket.
        """ 
        repo = Repository()
        return repo.get_shipping_methods(self.request.user, self.request.basket, 
                                         self.get_shipping_address())
    
    def post(self, request, *args, **kwargs):
        method_code = request.POST['method_code']
        co_data = CheckoutSessionData()
        co_data.use_shipping_method(method_code)
        return self.get_success_response()
        
    def get_success_response(self):
        return HttpResponseRedirect(reverse('oscar-checkout-payment-method'))


class PaymentMethodView(CheckoutView):
    """
    View for a user to choose which payment method(s) they want to use.
    
    This would include setting allocations if payment is to be split
    between multiple sources.
    """
    pass


class OrderPreviewView(CheckoutView):
    """
    View a preview of the order before submitting.
    """
    
    template_file = 'oscar/checkout/preview.html'
    
    def handle_GET(self):
        self.mark_step_as_complete(self.request)
        return TemplateResponse(self.request, self.template_file, self.context)


class PaymentDetailsView(CheckoutView):
    """
    For taking the details of payment and creating the order
    
    The class is deliberately split into fine-grained method, responsible for only one
    thing.  This is to make it easier to subclass and override just one component of
    functionality.
    """

    # Any payment sources should be added to this list as part of the
    # _handle_payment method.  If the order is placed successfully, then
    # they will be persisted.
    payment_sources = []

    def handle_GET(self):
        """
        This method needs to be overridden if there are any payment details
        to be taken from the user, such as a bankcard.
        """
        return self.handle_POST()
    
    def handle_POST(self):
        """
        This method is designed to be overridden by subclasses which will
        validate the forms from the payment details page.  If the forms are valid
        then the method can call submit()."""
        return self.submit(self.basket)
    
    def submit(self, basket, **kwargs):
        # We generate the order number first as this will be used
        # in payment requests (ie before the order model has been 
        # created).
        order_number = self.generate_order_number(basket)
        logger.info(_("Order #%s: beginning submission process" % order_number))
        
        # We freeze the basket to prevent it being modified once the payment
        # process has started.  If your payment fails, then the basket will
        # need to be "unfrozen".  We also store the basket ID in the session
        # so the it can be retrieved by multistage checkout processes.
        self.basket.freeze()
        self.request.session['checkout_basket_id'] = basket.id
        
        # Handle payment.  Any payment problems should be handled by the 
        # handle_payment method raise an exception, which should be caught
        # within handle_POST and the appropriate forms redisplayed.
        try:
            pre_payment.send_robust(sender=self, view=self)
            total_incl_tax, total_excl_tax = self.get_order_totals(basket)
            self.handle_payment(order_number, total_incl_tax, **kwargs)
            post_payment.send_robust(sender=self, view=self)
        except RedirectRequiredException, e:
            # Redirect required (eg PayPal, 3DS)
            return HttpResponseRedirect(e.url)
        except UnableToTakePaymentException, e:
            # Something went wrong with payment, need to show
            # error to the user.  This type of exception is supposed
            # to set a friendly error message.
            return self.handle_GET(error=e.message)
        except PaymentException:
            # Something went wrong which wasn't anticipated.
            return self.handle_GET(error="A problem occured processing payment.")
        else:
            # If all is ok with payment, place order
            return self.place_order(order_number, basket, total_incl_tax, total_excl_tax)
    
    def restore_frozen_basket(self):
        """
        Restores a frozen basket as the sole OPEN basket
        """
        fzn_basket = Basket._default_manager.get(pk=self.request.session['checkout_basket_id'])
        fzn_basket.thaw()
        fzn_basket.merge(self.request.basket)
        self.set_template_context(fzn_basket)
    
    def place_order(self, order_number, basket, total_incl_tax=None, total_excl_tax=None): 
        """
        Place the order
        
        We deliberately pass the basket in here as the one tied to the request
        isn't necessarily the correct one to use in placing the order.  This can
        happen when a basket gets frozen.
        """   
        if total_incl_tax is None or total_excl_tax is None:
            total_incl_tax, total_excl_tax = self.get_order_totals(basket)
        
        order = self.create_order_models(basket, order_number, total_incl_tax, total_excl_tax)
        self.save_payment_details(order)
        self.reset_checkout()
        
        logger.info(_("Order #%s: submitted successfully" % order_number))
        
        # Send confirmation message (normally an email)
        self.send_confirmation_message(order)
        
        # Save order id in session so thank-you page can load it
        self.request.session['checkout_order_id'] = order.id
        return HttpResponseRedirect(reverse('oscar-checkout-thank-you'))
    
    def generate_order_number(self, basket):
        generator = OrderNumberGenerator()
        return generator.order_number(basket)

    def handle_payment(self, order_number, total, **kwargs):
        """
        Handle any payment processing.  
        
        This method is designed to be overridden within your project.  The
        default is to do nothing.
        """
        pass

    def save_payment_details(self, order):
        """
        Saves all payment-related details. This could include a billing 
        address, payment sources and any order payment events.
        """
        self.save_payment_events(order)
        self.save_payment_sources(order)

    def create_billing_address(self):
        """
        Saves any relevant billing data (eg a billing address).
        """
        return None
    
    def save_payment_events(self, order):
        """
        Saves any relevant payment events for this order
        """
        pass

    def save_payment_sources(self, order):
        """
        Saves any payment sources used in this order.
        
        When the payment sources are created, the order model does not exist and 
        so they need to have it set before saving.
        """
        for source in self.payment_sources:
            source.order = order
            source.save()
    
    def reset_checkout(self):
        """Reset any checkout session state"""
        self.co_data.flush()
        self.request.session['checkout_basket_id'] = None
        ProgressChecker().all_steps_complete(self.request)
    
    def create_order_models(self, basket, order_number, total_incl_tax, total_excl_tax):
        """Writes the order out to the DB"""
        shipping_address = self.create_shipping_address()
        shipping_method = self.get_shipping_method(basket)
        billing_address = self.create_billing_address()
        status = self.get_initial_order_status(basket)
        return OrderCreator().place_order(self.request.user, 
                                         basket, 
                                         shipping_address, 
                                         shipping_method, 
                                         billing_address,
                                         total_incl_tax,
                                         total_excl_tax,
                                         order_number,
                                         status)
    
    def get_initial_order_status(self, basket):
        return None
    
    def get_shipping_address(self):
        addr_data = self.co_data.new_address_fields()
        addr_id = self.co_data.user_address_id()
        if addr_data:
            addr = ShippingAddress(**addr_data)
        elif addr_id:
            addr = UserAddress._default_manager.get(pk=addr_id)
        return addr
    
    def create_shipping_address(self):
        """Returns the shipping address"""
        addr_data = self.co_data.new_address_fields()
        addr_id = self.co_data.user_address_id()
        if addr_data:
            addr = self.create_shipping_address_from_form_fields(addr_data)
            self.create_user_address(addr_data)
        elif addr_id:
            addr = self.create_shipping_address_from_user_address(addr_id)
        else:
            raise AttributeError("No shipping address data found")
        return addr
    
    def create_shipping_address_from_form_fields(self, addr_data):
        """Creates a shipping address model from the saved form fields"""
        shipping_addr = ShippingAddress(**addr_data)
        shipping_addr.save() 
        return shipping_addr
    
    def create_user_address(self, addr_data):
        """
        For signed-in users, we create a user address model which will go 
        into their address book.
        """
        if self.request.user.is_authenticated():
            addr_data['user_id'] = self.request.user.id
            user_addr = UserAddress(**addr_data)
            # Check that this address isn't already in the db as we don't want
            # to fill up the customer address book with duplicate addresses
            try:
                UserAddress._default_manager.get(hash=user_addr.generate_hash())
            except ObjectDoesNotExist:
                user_addr.save()
    
    def create_shipping_address_from_user_address(self, addr_id):
        """Creates a shipping address from a user address"""
        address = UserAddress._default_manager.get(pk=addr_id)
        # Increment the number of orders to help determine popularity of orders 
        address.num_orders += 1
        address.save()
        
        shipping_addr = ShippingAddress()
        address.populate_alternative_model(shipping_addr)
        shipping_addr.save()
        return shipping_addr
    
    def send_confirmation_message(self, order):
        # Create order communication event
        try:
            event_type = CommunicationEventType._default_manager.get(code='order-placed')
        except CommunicationEventType.DoesNotExist:
            logger.error(_("Order #%s: unable to find 'order_placed' comms event" % order.number))
        else:
            if self.request.user.is_authenticated() and event_type.has_email_templates():
                logger.info(_("Order #%s: sending confirmation email" % order.number))
                
                # Send the email
                subject = event_type.get_email_subject_for_order(order)
                body = event_type.get_email_body_for_order(order)
                email = EmailMessage(subject, body, to=[self.request.user.email])
                email.send()
                
                # Record email against user for their email history
                Email._default_manager.create(user=self.request.user, 
                                              subject=email.subject,
                                              body_text=email.body)
                
                # Record communication event against order
                CommunicationEvent._default_manager.create(order=order, type=event_type)
        

class ThankYouView(DetailView):
    """
    Displays the 'thank you' page which summarises the order just submitted.
    """
    template_name = 'oscar/checkout/thank_you.html'
    context_object_name = 'order'
    
    def get_object(self):
        return Order._default_manager.get(pk=self.request.session['checkout_order_id'])
