"""Forms in a modal (``frontend/modal.js``): links with ``data-modal`` load
their form with the ``HX-Modal`` header into a ``<dialog>``, the form posts
there too. The views stay as they are: ``generic/object_form.html`` renders
only the form for these requests, and redirects (saving, also the login's)
become ``HX-Redirect``, which loads the page like without JavaScript.
Requests made by ``fetch`` follow redirects themselves, so they have to be
answered here."""

from django.http import HttpResponse


def is_modal(request):
    return request.headers.get("HX-Modal") == "true"


def modal_middleware(get_response):
    def middleware(request):
        response = get_response(request)
        if is_modal(request) and response.status_code in {301, 302, 303}:
            return HttpResponse(headers={"HX-Redirect": response["Location"]})
        return response

    return middleware


def context(request):
    return {"modal": is_modal(request)}
