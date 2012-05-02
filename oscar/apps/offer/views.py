from django.views.generic import ListView
from django.shortcuts import get_object_or_404
from django.db.models import get_model

from oscar.apps.offer.models import ConditionalOffer
Product = get_model('catalogue', 'Product')


class OfferDetailView(ListView):
    context_object_name = 'products'
    template_name = 'offer/detail.html'
    template_name_expired = 'offer/detail.html'
    paginate_by = 20

    def get(self, request, *args, **kwargs):
        self.offer = get_object_or_404(ConditionalOffer, id=self.kwargs['pk'])
        return super(OfferDetailView, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super(OfferDetailView, self).get_context_data(**kwargs)
        ctx['offer'] = self.offer
        ctx['upsell_message'] = self.offer.get_upsell_message(self.request.basket)
        return ctx

    def get_queryset(self):
        range = self.offer.condition.range
        if range.includes_all_products:
            return Product.browsable.all()
        return None
