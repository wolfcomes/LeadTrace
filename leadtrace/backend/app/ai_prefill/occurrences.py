"""Group source locators at the database's occurrence precision, preserving aliases."""
from decimal import Decimal,ROUND_HALF_UP


def occurrence_groups(locators):
    groups={}
    for item in locators:
        key=(item.compound_ref,item.page_number,*[getattr(item.bbox,k).quantize(Decimal('0.0000000001'),rounding=ROUND_HALF_UP) for k in ('x0','y0','x1','y1')])
        groups.setdefault(key,[]).append(item)
    return list(groups.values())


def _joined_context(group):
    contexts = list(dict.fromkeys(x.source_context.strip() for x in group if x.source_context and x.source_context.strip()))
    if len(group) > 1:
        contexts.extend('Source label: ' + label for label in dict.fromkeys(x.label.strip() for x in group if x.label and x.label.strip()))
    return '\n'.join(contexts) or None


def occurrence_context(group):
    """Keep the stored field exportable; full annotations live in delivery notes."""
    joined = _joined_context(group)
    if joined and len(joined) > 10000:
        return group[0].source_context
    return joined


def occurrence_notes(locators):
    return [{'code':'DUPLICATE_STRUCTURE_OCCURRENCE_MERGED','compound_ref':g[0].compound_ref,
             'page_number':g[0].page_number,'locator_refs':[x.ref for x in g],
             'message':'Repeated locators for the same compound, page and crop were stored as one occurrence; all locator refs and annotations were retained.',
             'extended_annotations':len(_joined_context(g) or '') > 10000,
             'annotations':[{'ref':x.ref,'label':x.label,'source_context':x.source_context} for x in g]}
            for g in occurrence_groups(locators) if len(g)>1]
