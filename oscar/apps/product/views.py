from django.conf import settings
from django.http import HttpResponse, Http404, HttpResponsePermanentRedirect, HttpResponseRedirect
from django.template import Context, loader, RequestContext
from django.shortcuts import get_object_or_404
from django.core.urlresolvers import reverse
from django.core.paginator import Paginator, InvalidPage, EmptyPage
from django.views.generic import ListView, DetailView
from django.template.response import TemplateResponse

from oscar.core.loading import import_module
from oscar.apps.product.signals import product_viewed, product_search

from django.db.models import get_model

item_model = get_model('product','item')
item_class_model = get_model('product', 'itemclass')


class ItemDetailView(DetailView):
    #template_name = "oscar/product/item.html"
    model = item_model
    view_signal = product_viewed
    template_folder = "oscar/product"
    _item = None
    
    def get(self, request, **kwargs):
        u"""
        Ensures that the correct URL is used
        """
        item = self.get_object()
        correct_path = item.get_absolute_url() 
        if correct_path != request.path:
            return HttpResponsePermanentRedirect(correct_path)
        response = super(ItemDetailView, self).get(request, **kwargs)
        
        # Send signal to record the view of this product
        self.view_signal.send(sender=self, product=self.object, user=request.user, request=request, response=response)
        return response;

    
    def get_template_names(self):
        """
        Returns a list of possible templates.
        
        We try 2 options before defaulting to oscar/product/detail.html:
        1). detail-for-upc-<upc>.html
        2). detail-for-class-<classname>.html
        
        This allows alternative templates to be provided for a per-product
        and a per-item-class basis.
        """    
        product = self.get_object()
        names = ['%s/detail-for-upc-%s.html' % (self.template_folder, product.upc), 
                 '%s/detail-for-class-%s.html' % (self.template_folder, product.item_class.name.lower()),
                 '%s/detail.html' % (self.template_folder)]
        return names


class ItemClassListView(ListView):
    u"""View products filtered by item-class."""
    context_object_name = "products"
    template_name = 'oscar/product/browse.html'
    paginate_by = 20

    def get_queryset(self):
        item_class = get_object_or_404(item_class_model, slug=self.kwargs['item_class_slug'])
        return item_model.browsable.filter(item_class=item_class).select_related('stockrecord')

class ProductListView(ListView):
    u"""A list of products"""
    context_object_name = "products"
    template_name = 'oscar/product/browse.html'
    paginate_by = 20
    search_signal = product_search

    def get_search_query(self):
        u"""Return a search query from GET"""
        q = None
        if 'q' in self.request.GET and self.request.GET['q']:
            q = self.request.GET['q'].strip()
        return q

    def get_queryset(self):
        u"""Return a set of products"""
        q = self.get_search_query()
        if q:
            # Send signal to record the view of this product
            self.search_signal.send(sender=self, query=q, user=self.request.user)
            
            return item_model.browsable.filter(title__icontains=q).select_related('stockrecord')
        else:
            return item_model.browsable.all().select_related('stockrecord')
        
    def get_context_data(self, **kwargs):
        context = super(ProductListView, self).get_context_data(**kwargs)
        q = self.get_search_query()
        if not q:
            context['summary'] = 'All products'
        else:
            context['summary'] = "Products matching '%s'" % q
            context['search_term'] = q
        return context
