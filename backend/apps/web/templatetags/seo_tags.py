import html

from django import template
from django.utils.html import strip_tags

register = template.Library()


class _CaptureNode(template.Node):
    def __init__(self, nodelist, var):
        self.nodelist, self.var = nodelist, var

    def render(self, context):
        # plain text, one line: the same words feed <title>, og:title, twitter:title (each output is escaped where it is used)
        text = html.unescape(strip_tags(self.nodelist.render(context)))
        context[self.var] = " ".join(text.split())
        return ""


@register.tag
def capture(parser, token):
    """{% capture as page_title %}{% block title %}...{% endblock %}{% endcapture %}

    Renders what is inside once, stores it as plain text in a variable and prints nothing. Lets a page write its title and
    description a single time while the head reuses them for the browser title, Open Graph and Twitter cards."""
    bits = token.split_contents()
    if len(bits) != 3 or bits[1] != "as":
        raise template.TemplateSyntaxError("usage: {% capture as variable_name %}...{% endcapture %}")
    nodelist = parser.parse(("endcapture",))
    parser.delete_first_token()
    return _CaptureNode(nodelist, bits[2])
