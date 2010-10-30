import math
from datetime import datetime, timedelta
from decimal import Decimal
import random

from django.core.urlresolvers import reverse
from django.conf import settings
from django.test import TestCase
from django.test.client import Client
from django.test.testcases import call_command

from nose.tools import *
from poseur.fixtures import load_fixtures
from pytz import timezone

from tiger.accounts.models import Site, TimeSlot, Schedule, Location
from tiger.core.exceptions import *
from tiger.core.forms import OrderForm
from tiger.core.messages import *
from tiger.core.models import Section, Item, Variant, Order
from tiger.utils.hours import DOW_CHOICES


def create_timeslots(schedule, dt, start_offset, stop_offset):
    for dow, display in DOW_CHOICES:
        TimeSlot.objects.create(
            dow=dow, schedule=schedule,
            start=(datetime.now() + timedelta(minutes=dt) - timedelta(minutes=start_offset)).time(),
            stop=(datetime.now() + timedelta(minutes=dt) + timedelta(minutes=stop_offset)).time()
        )


def setup_timeslots(dt):
    """Returns a callable to be passed to ``with_setup`` that generates time
    slots with offset of ``dt`` minutes.
    """
    def _setup():
        if not Site.objects.count():
            load_fixtures('tiger.fixtures')
        site = Site.objects.all()[0]
        location = site.location_set.all()[0]
        location.eod_buffer = 15
        location.tax_rate = '6.25'
        site.enable_orders = True
        site.save()
        schedule = location.schedule
        if schedule is None:
            schedule = location.schedule = Schedule.objects.create(site=site)
        location.save()
        create_timeslots(schedule, dt, 30, 30)
    return _setup


def setup_section_timeslots(dt):
    def _setup():
        setup_timeslots(dt)()
        site = Site.objects.all()[0]
        section = Section.objects.all()[0]
        schedule = section.schedule
        if schedule is None:
            schedule = Schedule.objects.create(site=site)
        section.schedule = schedule
        section.save()
        create_timeslots(schedule, dt, 30, 0)
    return _setup


def setup_item_timeslots(dt):
    def _setup():
        setup_timeslots(dt)()
        site = Site.objects.all()[0]
        item = Item.objects.all()[0]
        schedule = item.schedule
        if schedule is None:
            schedule = Schedule.objects.create(site=site)
        item.schedule = schedule
        item.save()
        create_timeslots(schedule, dt, 30, 0)
    return _setup


def setup_pricepoint_timeslots(dt):
    def _setup():
        setup_timeslots(dt)()
        site = Site.objects.all()[0]
        schedule = Schedule.objects.create(site=site)
        create_timeslots(schedule, dt, 30, 0)
        for item in site.item_set.all():
            item.variant_set.all().delete()
            item.archived = False
            item.out_of_stock = False
            item.save()
            # no schedule for one price point
            Variant.objects.create(description='large', item=item, price=Decimal('5.00'))
            v = Variant.objects.create(description='small', item=item, price=Decimal('3.00'), schedule=schedule)
    return _setup
            

def teardown_timeslots():
    for section in Section.objects.all():
        section.schedule = None
        section.save()
    for item in Item.objects.all():
        item.schedule = None
        item.save()
    for location in Location.objects.all():
        location.schedule = None
        location.save()
    Schedule.objects.all().delete()
        

@with_setup(setup_timeslots(0), teardown_timeslots)
@raises(NoOnlineOrders)
def test_online_ordering_disabled():
    site = Site.objects.all()[0]
    site.enable_orders = False
    assert site.is_open(site.location_set.all()[0])


@with_setup(setup_timeslots(0), teardown_timeslots)
def test_online_ordering_enabled():
    site = Site.objects.all()[0]
    site.enable_orders = True
    site.save()
    assert site.is_open(site.location_set.all()[0])


@with_setup(setup_timeslots(90), teardown_timeslots)
@raises(RestaurantNotOpen)
def test_restaurant_is_closed_early():
    site = Site.objects.all()[0]
    assert site.is_open(site.location_set.all()[0])


@with_setup(setup_timeslots(-90), teardown_timeslots)
@raises(RestaurantNotOpen)
def test_restaurant_is_closed_late():
    site = Site.objects.all()[0]
    assert site.is_open(site.location_set.all()[0])


@with_setup(setup_timeslots(-20), teardown_timeslots)
@raises(ClosingTimeBufferError)
def test_within_closing_buffer():
    site = Site.objects.all()[0]
    assert site.is_open(site.location_set.all()[0])


@with_setup(setup_section_timeslots(10), teardown_timeslots)
def test_section_open():
    section = Section.objects.all()[0]
    assert section.is_available(Location.objects.all()[0])


@with_setup(setup_section_timeslots(-10), teardown_timeslots)
@raises(SectionNotAvailable)
def test_section_closed():
    section = Section.objects.all()[0]
    assert section.is_available(Location.objects.all()[0])


@with_setup(setup_section_timeslots(-10), teardown_timeslots)
@raises(SectionNotAvailable)
def test_item_with_section_closed():
    item = Item.objects.all()[0]
    assert item.is_available(Location.objects.all()[0])


@with_setup(setup_item_timeslots(-10), teardown_timeslots)
@raises(ItemNotAvailable)
def test_item_schedule_closed():
    item = Item.objects.all()[0]
    assert item.is_available(Location.objects.all()[0])


@raises(ItemNotAvailable)
def test_item_archived():
    item = Item.objects.all()[0]
    item.archived = True
    assert item.is_available(Location.objects.all()[0])


@raises(ItemNotAvailable)
def test_item_out_of_stock():
    item = Item.objects.all()[0]
    item.out_of_stock = True
    assert item.is_available(Location.objects.all()[0])


def test_item_available():
    item = Item.objects.all()[0]
    item.out_of_stock = False
    item.archived = False
    assert item.is_available(Location.objects.all()[0])


@with_setup(setup_pricepoint_timeslots(10), teardown_timeslots)
def test_pricepoint_open():
    item = Item.objects.all()[0]
    assert item.variant_set.filter(description='small')[0].is_available(Location.objects.all()[0])


@with_setup(setup_pricepoint_timeslots(-10), teardown_timeslots)
@raises(PricePointNotAvailable)
def test_pricepoint_closed():
    item = Item.objects.all()[0]
    assert item.variant_set.filter(description='small')[0].is_available(Location.objects.all()[0])


def data_for_order_form(item, **variant_kwds):
    data = {'quantity': random.randint(1, 5)}
    if item.variant_set.count():
        data['variant'] = item.variant_set.filter(**variant_kwds)[0].id
    for sidegroup in item.sidedishgroup_set.all():
        if sidegroup.sidedish_set.count() > 1:
            data['side_%d' % sidegroup.id] = sidegroup.sidedish_set.order_by('?')[0].id 
    return data

class PricePointNotAvailableTestCase(TestCase):
    def setUp(self):
        setup_pricepoint_timeslots(-10)()
        self.client = Client(HTTP_HOST='foo.takeouttiger.com')
        self.client.get('/')
        self.item = Item.objects.order_by('?')[0]

    def test_scheduled_pricepoint_invalid(self):
        order_url = reverse('order_item', kwargs={'section_id': self.item.section.id, 'section_slug': self.item.section.slug, 'item_id': self.item.id, 'item_slug': self.item.slug})
        response = self.client.post(order_url, data_for_order_form(self.item, description='small'), follow=True)
        pricepoint = self.item.variant_set.filter(description='small')[0]
        pricepoint_error_msg = PRICEPOINT_NOT_AVAILABLE % (pricepoint.description, pricepoint.schedule.display)
        self.assertContains(response, pricepoint_error_msg)
        
    def test_nonscheduled_pricepoint_valid(self):
        order_url = reverse('order_item', kwargs={'section_id': self.item.section.id, 'section_slug': self.item.section.slug, 'item_id': self.item.id, 'item_slug': self.item.slug})
        response = self.client.post(order_url, data_for_order_form(self.item, description='large'), follow=True)
        pricepoint = self.item.variant_set.filter(description='large')[0]
        pricepoint_error_msg = PRICEPOINT_NOT_AVAILABLE % (pricepoint.description, '')
        self.assertNotContains(response, pricepoint_error_msg)


class ItemDisplayTestCase(TestCase):
    def setUp(self):
        setup_timeslots(0)()
        self.client = Client(HTTP_HOST='foo.takeouttiger.com')
        self.client.get('/')
        self.item = Variant.objects.all()[0].item
        self.item.update_price()

    def test_available(self):
        self.item.archived = self.item.out_of_stock = False
        self.item.save()
        response = self.client.get(self.item.get_absolute_url())
        self.assertNotContains(response, ITEM_NOT_AVAILABLE % self.item.name)

    def test_archived(self):
        self.item.archived = True
        self.item.save()
        response = self.client.get(self.item.get_absolute_url())
        self.assertContains(response, ITEM_NOT_AVAILABLE % self.item.name)

    def test_out_of_stock(self):
        self.item.out_of_stock = True
        self.item.save()
        response = self.client.get(self.item.get_absolute_url())
        self.assertContains(response, ITEM_NOT_AVAILABLE % self.item.name)


def setup_order_validation():
    setup_timeslots(0)()
    site = Site.objects.all()[0]
    location = site.location_set.all()[0]
    location.lead_time = 30
    location.delivery_lead_time = 60
    location.save()

def set_timezone(tz):
    site = Site.objects.all()[0]
    location = site.location_set.all()[0]
    location.timezone = tz
    location.save()


def get_order_form(ready_by, order_method):
    site = Site.objects.all()[0]
    location = site.location_set.all()[0]
    form = OrderForm({
        'name': 'John Smith',
        'phone': '12345',
        'ready_by': ready_by if isinstance(ready_by, basestring) else ready_by.strftime('%I:%M %p'),
        'method': order_method,
    }, site=site, location=location)
    form.total = '40.00'
    return form

def invalid_pickup_time(tz):
    site = Site.objects.all()[0]
    location = site.location_set.all()[0]
    server_tz = timezone(settings.TIME_ZONE)
    site_tz = timezone(tz)
    form = get_order_form(server_tz.localize(datetime.now()).astimezone(site_tz), Order.METHOD_TAKEOUT)
    assert_false(form.is_valid())
    assert_true('Takeout orders must be placed %d minutes in advance.' % location.lead_time in form.non_field_errors())

def valid_pickup_time(tz):
    # ready_by will not have resolution of seconds
    site = Site.objects.all()[0]
    location = site.location_set.all()[0]
    server_tz = timezone(settings.TIME_ZONE)
    site_tz = timezone(tz)
    ready_by = server_tz.localize((datetime.now() + timedelta(minutes=(location.lead_time + 5))).replace(second=0, microsecond=0)).astimezone(site_tz)
    form = get_order_form(ready_by, Order.METHOD_TAKEOUT)
    assert_true(form.is_valid())
    order = form.save(commit=False)
    order.total = '10.00'
    order.tax = '4.00'
    order.cart = {}
    order.site = site
    order.save()

@with_setup(lambda: (setup_order_validation(), set_timezone('US/Eastern')), teardown_timeslots)
def test_invalid_pickup_time_server_tz():
    invalid_pickup_time('US/Eastern')

@with_setup(lambda: (setup_order_validation(), set_timezone('US/Pacific')), teardown_timeslots)
def test_invalid_pickup_time_east_tz():
    invalid_pickup_time('US/Pacific')

@with_setup(lambda: (setup_order_validation(), set_timezone('Canada/Newfoundland')), teardown_timeslots)
def test_invalid_pickup_time_west_tz():
    invalid_pickup_time('Canada/Newfoundland')

@with_setup(lambda: (setup_order_validation(), set_timezone('US/Eastern')), teardown_timeslots)
def test_valid_pickup_time_server_tz():
    valid_pickup_time('US/Eastern')

@with_setup(lambda: (setup_order_validation(), set_timezone('US/Pacific')), teardown_timeslots)
def test_valid_pickup_time_east_tz():
    valid_pickup_time('US/Pacific')

@with_setup(lambda: (setup_order_validation(), set_timezone('Canada/Newfoundland')), teardown_timeslots)
def test_valid_pickup_time_west_tz():
    valid_pickup_time('Canada/Newfoundland')

@with_setup(lambda: (setup_order_validation(), set_timezone('Canada/Newfoundland')), teardown_timeslots)
def test_gibberish_pickup_time():
    form = get_order_form('foobarbaz', Order.METHOD_TAKEOUT)
    assert_false(form.is_valid())
    assert_true('Please entire a clock time, like "12:30 PM".' in form['ready_by'].errors)

@with_setup(lambda: (setup_order_validation(), set_timezone('Canada/Newfoundland')), teardown_timeslots)
def test_blank_pickup_time():
    form = get_order_form('', Order.METHOD_TAKEOUT)
    assert_false(form.is_valid())
    assert_true('This field is required.' in form['ready_by'].errors)
