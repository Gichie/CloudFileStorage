import logging
import urllib

from django.urls import reverse

logger = logging.getLogger(__name__)


def encode_path_for_url(unencoded_path, view_name):
    encoded_path = urllib.parse.quote_plus(unencoded_path)
    return f"{reverse(view_name)}?path={encoded_path}"
