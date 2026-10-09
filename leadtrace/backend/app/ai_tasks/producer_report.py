"""Bounded producer diagnostics for Admin draft delivery; no model logs or source reads."""
from hashlib import sha256
from pathlib import Path
from app.ai_prefill.assistance_coverage import CompoundInventory
from app.ai_prefill.assistance_self_check import SourceSelfReview,self_check_candidate


def read_artifact(directory:Path,name:str)->bytes:
    path=directory/name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory.resolve()) or path.stat().st_size>8*1024*1024:
        raise ValueError('Diagnostic artifact missing or unsafe')
    return path.read_bytes()


def producer_report(directory,candidate,raw):
    issues=[];checks=[];coverage={'expected':0,'reviewed':0,'missing':[]};coverage_known=False
    review=None;inventory=None
    try:
        review=SourceSelfReview.model_validate_json(read_artifact(directory,'outputs/self-review.json'))
        if review.candidate_file_sha256!=sha256(raw).hexdigest():
            raise ValueError('Stale source review')
        checks=[{'check_id':c.check_id,'status':c.status,'details':c.details[:4000]} for c in review.checks]
    except (ValueError,OSError):
        review=None
        issues.append({'code':'SELF_REVIEW_MISSING','path':'self_review','severity':'blocking','message':'Producer self-review is missing, invalid or bound to a different candidate; source checks remain unverified.'})
    try:
        inventory=CompoundInventory.model_validate_json(read_artifact(directory,'outputs/compound-inventory.json'))
        report=self_check_candidate(candidate,inventory,candidate_file_bytes=raw,self_review=review)
        issues.extend(report['issues']);cov=report['compound_coverage'];coverage_known=True
        missing=[*cov['missing_labels'],*[x['label'] for x in cov['ambiguous_matches']]]
        coverage={'expected':cov['required_count'],'reviewed':cov['covered_count'],
                  'missing':[{'domain':'compound','ref':label[:500]} for label in missing[:5000]]}
    except (ValueError,OSError):
        issues.append({'code':'INVENTORY_UNAVAILABLE','path':'compound_inventory','severity':'blocking','message':'A valid inventory for this source is unavailable; whole-paper Compound coverage is unknown.'})
        issues.extend(self_check_candidate(candidate,None,candidate_file_bytes=raw,self_review=review)['issues'])
    issues.extend({'code':'DECLARED_OMISSION','path':x.path,'severity':'blocking','message':x.reason,'source_locator':x.source_locator} for x in candidate.omissions)
    # Keep reports bounded and allowlisted: never return arbitrary sidecars/logs.
    unique={(x['code'],x['path'],x['message']):x for x in issues};issues=list(unique.values())
    blocking=sum(x['severity']=='blocking' for x in issues)
    findings=[{'domain':x['code'],'ref':x['path'][:500],'verdict':x['severity'],'reason':x['message'][:4000],**({'source_locator':x['source_locator']} if x.get('source_locator') else {})} for x in issues[:1000]]
    result={'report_kind':'prefill','candidate_file_sha256':sha256(raw).hexdigest(),
        'status':'needs_revision' if blocking else 'ready_for_independent_review','scientific_approval':False,
        'coverage':coverage,'coverage_known':coverage_known,'checks':checks,'findings':findings,
        'issue_counts':{'blocking':blocking,'review':len(issues)-blocking},'findings_total':len(issues),
        'findings_truncated':len(issues)>len(findings)}

    from app.ai_tasks.report_overview import build_overview
    result['overview']=build_overview(candidate,producer_report=result,inventory=inventory)
    return result
