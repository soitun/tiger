import hashlib
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.sessions.models import Session

from tiger.accounts.middleware import DomainDetectionMiddleware
from tiger.core.models import Item

class Cart(object):
    contents = {}

    def __init__(self, session):
        self.session = session
        self.contents = session.get_decoded()

    def __iter__(self):
        """Iterating over the cart returns a list of tuples consisting of
        the Item in the cart and the corresponding quantity.
        """
        return iter((Item.objects.get(id=k), v) for k, v in self.contents.items())

    def __len__(self):
        return len(self.contents)

    def add(self, obj_id, qty):
        contents = self.contents
        if contents.has_key(obj_id):
            contents[obj_id] = contents[obj_id] + qty
        else:
            contents[obj_id] = qty
        self.session.session_data = Session.objects.encode(contents)
        self.session.save()

    def remove(self, obj_id):
        contents = self.contents
        contents.pop(obj_id, None)
        self.session.session_data = Session.objects.encode(contents)
        self.session.save()

    def clear(self):
        self.session.session_data = Session.objects.encode({})
        self.session.save()


class ShoppingCartMiddleware(object):
    """Middleware to add a ``Cart`` object to the request.  Must come after the
    ``SiteDetectionMiddleware`` because the cart needs the site object to be
    able to keep transactions for different sites separate.  
    """
    def process_request(self, request):
        cookie_name, session_key = self._get_cookie_pair(request)
        if session_key:
            s = Session.objects.get(session_key=session_key)
            request.cart = Cart(s)

    def process_response(self, request, response):
        cookie_name, session_key = self._get_cookie_pair(request)
        if session_key is None:
            session_key = hashlib.md5(
                cookie_name + settings.SECRET_KEY + str(time.time())
            ).hexdigest()
            Session.objects.create(
                session_key=session_key, 
                session_data=Session.objects.encode({}), 
                expire_date=(datetime.now() + timedelta(days=7)))
            response.set_cookie(str(cookie_name), session_key)
        return response

    def _get_cookie_pair(self, request):
        site = DomainDetectionMiddleware.get_site(request)
        if site is None:
            # fake out the cookie setter if we're on takeouttiger.com
            return True, False
        cookie_name = 'takeouttiger_%s' % site.domain
        session_key = request.COOKIES.get(cookie_name)
        return cookie_name, session_key