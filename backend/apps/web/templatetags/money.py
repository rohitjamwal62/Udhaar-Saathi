from django import template

register = template.Library()


@register.filter
def rupees(paise) -> str:
    """Format paise as Indian-grouped rupees, e.g. 12345678 -> Rs 1,23,456.78"""
    paise = int(paise or 0)
    sign = "-" if paise < 0 else ""
    r, p = divmod(abs(paise), 100)
    s = str(r)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{sign}Rs {s}.{p:02d}"


@register.filter
def absval(n) -> int:
    return abs(int(n or 0))
