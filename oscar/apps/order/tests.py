from decimal import Decimal as D
import hashlib

from django.test import TestCase
from django.conf import settings

from oscar.apps.address.models import Country
from oscar.apps.basket.models import Basket
from oscar.apps.order.models import ShippingAddress, Order, Line, ShippingEvent, ShippingEventType, ShippingEventQuantity
from oscar.test.helpers import create_order, create_product

ORDER_PLACED = 'order_placed'


class ShippingAddressTest(TestCase):
    fixtures = ['countries.json']
    
    def test_titleless_salutation_is_stripped(self):
        country = Country.objects.get(iso_3166_1_a2='GB')
        a = ShippingAddress.objects.create(last_name='Barrington', line1="75 Smith Road", postcode="N4 8TY", country=country)
        self.assertEquals("Barrington", a.salutation())
    

class OrderTest(TestCase):

    def setUp(self):
        self.order = create_order(number='100002')
        self.order_placed,_ = ShippingEventType.objects.get_or_create(code='order_placed', 
                                                                      name='Order placed')
        
    def event(self, type):
        """
        Creates an order-level shipping event
        """
        type = self.order_placed
        event = ShippingEvent.objects.create(order=self.order, event_type=type)
        for line in self.order.lines.all():
            ShippingEventQuantity.objects.create(event=event, line=line)  
        
    def test_shipping_status_is_empty_with_no_events(self):
        self.assertEquals("", self.order.shipping_status)

    def test_shipping_status_after_one_order_level_events(self):
        self.event(ORDER_PLACED)
        self.assertEquals("Order placed", self.order.shipping_status)

    def test_order_hash_generation(self):
        order = create_order()
        expected = hashlib.md5("%s%s" % (order.number, settings.SECRET_KEY)).hexdigest()
        self.assertEqual(expected, order.verification_hash())

        
class LineTest(TestCase):

    def setUp(self):
        basket = Basket()
        basket.add_product(create_product(price=D('10.00')), 4)
        self.order = create_order(number='100002', basket=basket)
        self.line = self.order.lines.all()[0]
        self.order_placed,_ = ShippingEventType.objects.get_or_create(code='order_placed', 
                                                                      name='Order placed')
        self.dispatched,_ = ShippingEventType.objects.get_or_create(code='dispatched', 
                                                                    name='Dispatched')

    def event(self, type, quantity=None):
        """
        Creates a shipping event for the test line
        """
        event = ShippingEvent.objects.create(order=self.order, event_type=type)
        if quantity == None:
            quantity = self.line.quantity
        event_quantity = ShippingEventQuantity.objects.create(event=event, line=self.line, quantity=quantity)

    def test_shipping_status_is_empty_to_start_with(self):
        self.assertEquals('', self.line.shipping_status)
        
    def test_shipping_status_after_full_line_event(self):
        self.event(self.order_placed)
        self.assertEquals(self.order_placed.name, self.line.shipping_status)    
        
    def test_shipping_status_after_two_full_line_events(self):
        type1 = self.order_placed
        self.event(type1)
        type2 = self.dispatched
        self.event(type2)
        self.assertEquals(type2.name, self.line.shipping_status) 
        
    def test_shipping_status_after_partial_line_event(self):
        type = self.order_placed
        self.event(type, 3)
        expected = "%s (%d/%d items)" % (type.name, 3, self.line.quantity)
        self.assertEquals(expected, self.line.shipping_status) 
        
    def test_has_passed_shipping_status_after_full_line_event(self):
        type = self.order_placed
        self.event(type)
        self.assertTrue(self.line.has_shipping_event_occurred(type)) 
        
    def test_has_passed_shipping_status_after_partial_line_event(self):
        type = self.order_placed
        self.event(type, self.line.quantity - 1)
        self.assertFalse(self.line.has_shipping_event_occurred(type)) 
        
    def test_has_passed_shipping_status_after_multiple_line_event(self):
        event_types = [ShippingEventType.objects.get(code='order_placed'),
                        ShippingEventType.objects.get(code='dispatched')]
        for type in event_types:
            self.event(type)
        for type in event_types:
            self.assertTrue(self.line.has_shipping_event_occurred(type))
            
    def test_inconsistent_shipping_status_setting(self):
        type = self.order_placed
        self.event(type, self.line.quantity - 1)
        
        with self.assertRaises(ValueError):
            self.event(type, self.line.quantity)
        
    def test_inconsistent_shipping_quantities(self):
        type = ShippingEventType.objects.get(code='order_placed')
        self.event(type, self.line.quantity - 1)
        
        with self.assertRaises(ValueError):
            # Total quantity is too high
            self.event(type, 2)
        
        
class ShippingEventQuantityTest(TestCase):

    def setUp(self):
        basket = Basket()
        basket.add_product(create_product(price=D('10.00')), 4)
        self.order = create_order(number='100002', basket=basket)
        self.line = self.order.lines.all()[0]
        self.order_placed,_ = ShippingEventType.objects.get_or_create(code='order_placed', 
                                                                      name='Order placed')

    def test_quantity_defaults_to_all(self):
        type = self.order_placed
        event = ShippingEvent.objects.create(order=self.order, event_type=type)
        event_quantity = ShippingEventQuantity.objects.create(event=event, line=self.line)
        self.assertEquals(self.line.quantity, event_quantity.quantity)
    
   