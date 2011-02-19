from decimal import Decimal

from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.template.defaultfilters import slugify

from oscar.shipping.methods import ShippingMethod


class AbstractMethod(models.Model, ShippingMethod):
    u"""
    Standard shipping method
    
    This method has two components: 
    * a charge per order
    * a charge per item
    
    Many sites use shipping logic which fits into this system.  However, for more
    complex shipping logic, a custom shipping method object will need to be provided
    that subclasses ShippingMethod.
    """
    code = models.CharField(max_length=128, unique=True)
    name = models.CharField(_("Name"), max_length=128)
    description = models.TextField(_("Description"), blank=True)
    price_currency = models.CharField(max_length=12, default='GBP')
    price_per_order = models.DecimalField(decimal_places=2, max_digits=12, default=Decimal('0.00'))
    price_per_item = models.DecimalField(decimal_places=2, max_digits=12, default=Decimal('0.00'))
    
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = slugify(self.name)
        super(AbstractMethod, self).save(*args, **kwargs)
    
    class Meta:
        abstract = True
        
    def __unicode__(self):
        return self.name
    
    def set_basket(self, basket):
        self._basket = basket
    
    def basket_charge_incl_tax(self):
        charge = self.price_per_order
        for line in self._basket.lines.all():
            charge += line.quantity * self.price_per_item
        return charge
    
    def basket_charge_excl_tax(self):
        # @todo store tax amounts?
        return self.basket_charge_incl_tax()