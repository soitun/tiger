from django.http import HttpResponse, HttpResponseRedirect
from django.views.generic.simple import direct_to_template
from django.utils import simplejson as json

from tiger.stork import Stork
from tiger.stork.models import FontStack

    
def script_tag(request):
    stork = Stork(request.site.theme)
    return direct_to_template(request, template='stork/main.js', extra_context={
        'swatch_json': stork.swatch_json(),
        'font_json': stork.font_json()
    })

def font_css(request, selection_key, selected=None):
    stork = Stork(request.site.theme)
    component = stork[selection_key]
    if selected is not None:
        css = component.get_css(FontStack.objects.get(id=selected))
    else:
        css = component.get_css()
    response = HttpResponse(mimetype='text/css')
    response.write(css)
    return response

def stage_image(request, key):
    stork = Stork(request.site.theme)
    component = stork[key]
    form = component.form_instance(request.POST, request.FILES)
    form.save()
    return HttpResponse(json.dumps({
      'style_tag': '#' + component.style_tag_id,
      'css': component.get_css(),
      'component': key,
      'url': component.instance.staged_image.url
    }))

def remove_image(request, key):
    stork = Stork(request.site.theme)
    component = stork[key]
    instance = component.instance
    real_delete = False
    if bool(instance.staged_image) and not request.POST.has_key('%s-stale' % key):
        instance.staged_image.delete()
    else:
        real_delete = True
    return HttpResponse(json.dumps({
      'style_tag': '#' + component.style_tag_id,
      'css': '' if real_delete else component.get_css(),
      'component': key,
      'delete': real_delete,
    }))

def image_css(request, key):
    stork = Stork(request.site.theme)
    component = stork[key]
    css = component.get_css(request.POST.get('tiling'))
    return HttpResponse(json.dumps({
        'css': css,
        'style_tag': '#' + component.style_tag_id
    }))


def save(request, redirect_to, callback=None):
    stork = Stork(request.site.theme)
    stork.save(request.POST, request.FILES)
    return HttpResponse("OK")


def preview_html(request, key):
    stork = Stork(request.site.theme)
    stork[key].save(request.POST)
    return HttpResponseRedirect(request.META['HTTP_REFERER'])


def revert_html(request, key):
    stork = Stork(request.site.theme)
    stork[key].revert()
    return HttpResponseRedirect(request.META['HTTP_REFERER'])
