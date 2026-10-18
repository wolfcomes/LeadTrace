import pytest
from app.papers.models import Paper


@pytest.mark.parametrize('reviewer_rounds', [False, True])
def test_submission_filters_use_current_catalog_and_preserve_rounds(publication_fixture, reviewer_rounds):
    f=publication_fixture
    submission=f.submit()
    f.login('publication.admin')
    with f.session_factory.begin() as s:
        paper=s.get(Paper,f.paper_id)
        paper.journal='Current catalog journal';paper.volume='S2';paper.issue='3-4';paper.publication_year=2025
    path='/api/v2/admin/submissions'
    params={'reviewer_rounds':str(reviewer_rounds).lower(),'journal':'Current catalog journal','volume':'S2','issue':'3-4',
        'year_from':2025,'year_to':2025,'assignment_status':'assigned','prefill_status':'not_started'}
    result=f.client.get(path,params=params)
    assert result.status_code==200
    assert result.json()['total']==1
    assert result.json()['items'][0]['submission_id']==str(submission.id)
    for key,value in [('journal','Wrong'),('year_to',2024),('volume','1'),('issue','1'),('assignment_status','unassigned'),('prefill_status','failed')]:
        mismatch={**params,key:value}
        if key=='year_to':mismatch.pop('year_from')
        response=f.client.get(path,params=mismatch)
        assert response.status_code==200
        assert response.json()['total']==0
