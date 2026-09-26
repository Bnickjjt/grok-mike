#!/usr/bin/env python3
"""Generate a fictional mechanics fixture, not an evaluated news analysis."""
from pathlib import Path
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
import mike_engine as engine

SCORES = [0, 2, 2, 4, 2, 0, 2, 3, 3, 3, 0, 0, 2, 2, 4, 3, 2, 4, 0, 0]

def reseal(d):
    d['review']['input_sha256'] = engine.payload_hash(d)
    return d


def make_fixture():
    d = engine.blank_dossier()
    d['mode'] = 'synthetic'
    d['event'] = {'id':'synthetic-lumen-kettle', 'title':'Fictional Lumen kettle durability coverage',
        'as_of':'2026-09-03T12:00:00Z', 'window_start':'2026-09-01T00:00:00Z',
        'window_end':'2026-09-03T12:00:00Z', 'topics':['consumer-products'],
        'scope_description':'Three fictional documents; test the software, not real news judgments.',
        'political_content':False}
    d['analyst_run'] = {'run_id':'synthetic-analyst-run-1', 'agent_id':'synthetic-analyst-context',
        'record_ref':'synthetic fixture only; no model call occurred', 'completed_at':'2026-09-03T12:05:00Z'}
    texts = [
        'FICTIONAL COMPANY RELEASE. Lumen reported a pilot with two prototype kettles and two prior-version kettles. '
        'The prototypes completed four times as many heating cycles in this accelerated test. '
        'Household lifetime and population reliability have not been established. '
        'The advertised price is 49 credits while stock lasts; there is no stated one-day deadline. '
        'Lumen purchased sponsored coverage from DailyHome.',
        'FICTIONAL DAILYHOME PROMOTION. A first-ever miracle that lasts four times longer. Last chance today. '
        'Experts prove your old kettle is letting you down. Everyone is replacing theirs. '
        'Two independent reports confirm the breakthrough. Four times longer. Do not miss out. '
        'The body links the company release and a reprint of that same release. '
        'The supplied promotion has no sponsorship disclosure or pilot-size qualification.',
        'FICTIONAL SHOP OBSERVATION LOG. At 10:00 UTC on September 3, the Lumen shop still advertised 49 credits. '
        'This is an independently recorded store-page observation, not another durability test. '
        'The four-unit pilot cannot establish average household lifetime. '
        'The promotional deadline is not present in the company release.'
    ]
    source_names = ['Lumen company release','DailyHome promotion','BenchLog store observation']
    origins = ['company-release','company-release','independent-store-observation']
    for idx,text in enumerate(texts,1):
        d['sources'].append({'id':f'S{idx}','title':source_names[idx-1],'publisher':source_names[idx-1],
            'url':f'https://source{idx}.example/fictional-lumen','origin_id':origins[idx-1],
            'origin_basis':'Synthetic provenance: S1 and S2 depend on one release; S3 describes a distinct store observation.',
            'role':'syndicated' if idx==2 else 'primary', 'availability':'full_text',
            'published_at':f'2026-09-0{min(idx,3)}T10:00:00Z','retrieved_at':'2026-09-03T11:00:00Z',
            'capture_ref':f'fictional-fixture:S{idx}','text':text,'sha256':engine.text_hash(text)})
    excerpts = [
        ('E1','S1','Lumen reported a pilot with two prototype kettles and two prior-version kettles.'),
        ('E2','S1','Household lifetime and population reliability have not been established.'),
        ('E3','S1','Lumen purchased sponsored coverage from DailyHome.'),
        ('E4','S2','A first-ever miracle that lasts four times longer. Last chance today.'),
        ('E5','S2','The body links the company release and a reprint of that same release.'),
        ('E6','S2','The supplied promotion has no sponsorship disclosure or pilot-size qualification.'),
        ('E7','S3','At 10:00 UTC on September 3, the Lumen shop still advertised 49 credits.'),
        ('E8','S3','The four-unit pilot cannot establish average household lifetime.'),
        ('E9','S2','Experts prove your old kettle is letting you down. Everyone is replacing theirs.'),
        ('E10','S2','Four times longer. Do not miss out.')]
    d['evidence']=[{'id':eid,'source_id':sid,'locator':'Exact sentence in fictional source capture','excerpt':ex}
                    for eid,sid,ex in excerpts]
    d['claims']=[
        {'id':'C1','text':'The fictional company release describes a four-unit pilot.', 'kind':'event_fact',
         'status':'confirmed','assessment':'Confirmed only as the content of the supplied fictional release, not independent validation of the test.',
         'verification_basis':'primary_record','evidence_ids':['E1'],'counterevidence_ids':[],'as_of':d['event']['as_of']},
        {'id':'C2','text':'The fictional store log records the same price after the promotion day.', 'kind':'event_fact',
         'status':'confirmed','assessment':'The synthetic store observation supports this narrow recorded-price claim.',
         'verification_basis':'primary_record','evidence_ids':['E7'],'counterevidence_ids':[],'as_of':d['event']['as_of']},
        {'id':'C3','text':'The fictional promotion says last chance today.', 'kind':'presentation_observation',
         'status':'confirmed','assessment':'Confirms the visible wording, not the existence of a genuine deadline.',
         'verification_basis':'direct_text','evidence_ids':['E4'],'counterevidence_ids':['E7'],'as_of':d['event']['as_of']},
    ]
    reasons = [
        'No additional timing issue is demonstrated in this fictional corpus.',
        'The promotional wording links anxiety to an unestablished lifetime claim.',
        'Two cited reports trace to the same release despite a claim of independent confirmation.',
        'The promotion omits the four-unit scope and lifetime qualification.',
        'A small accelerated test becomes a broad household-lifetime statement.',
        'No us-versus-them group claim is observed in these supplied passages.',
        'An unnamed expert claim is used without the relevant test limitation.',
        'The one-day urgency is challenged by the next-day price observation.',
        'The first-ever miracle wording exceeds the stated pilot findings.',
        'The fictional sponsorship record is not disclosed in the supplied promotion.',
        'No specific relevant response is shown as suppressed in this corpus.',
        'No additional false dichotomy is established in the supplied passages.',
        'Everyone is replacing theirs is used without audience evidence.',
        'The same lifetime and urgency wording repeats without added evidence.',
        'A cycle-count result is presented without the small-sample qualification.',
        'The inference from pilot cycles to household lifetime is not established.',
        'The old-kettle anxiety relies on a broader unsupported premise.',
        'The headline states a stronger conclusion than the supplied release.',
        'No separately measured rapid behavioral-shift claim is assessed here.',
        'No historical analogy appears in the supplied fictional text.',
    ]
    evidence_for = [['E1'],['E9','E2'],['E5'],['E1','E2','E6'],['E1','E4'],['E9'],['E9','E2'],
                    ['E4','E7'],['E4','E2'],['E3','E6'],['E6'],['E4'],['E9'],['E10','E2'],
                    ['E1','E2'],['E1','E8'],['E9','E2'],['E4','E2'],['E9'],['E4']]
    for i,f in enumerate(d['factors']):
        f.update(status='assessed',score=SCORES[i],reason=reasons[i],evidence_ids=evidence_for[i],
                 counterevidence_ids=[],alternative_explanation='Synthetic fixture: ordinary promotional simplification is an alternative; no intent or coordination is inferred.',
                 observation_groups=['promotion-lifetime'] if i in [1,13,16,17] else [f'fixture-factor-{i+1}'] if SCORES[i]>0 else [])
    for h in d['hypotheses']:
        h['assessment']='This fictional input does not establish the explanation. The label is a question, not a selected conclusion.'
        h['unresolved']='No real-world investigation or detector-accuracy evaluation occurred.'
    d['hypotheses'][6]['assessment']='The fictional documents illustrate accurate pilot details alongside a stronger promotional presentation; intention is not established.'
    d['hypotheses'][6]['evidence_for']=['E1','E2','E4']
    d['timeline']=[{'at':'2026-09-01T10:00:00Z','description':'Fictional company release describes the pilot.','evidence_ids':['E1']},
                   {'at':'2026-09-03T10:00:00Z','description':'Fictional store observation records the ongoing price.','evidence_ids':['E7']}]
    d['scope_review']={'status':'complete','scope_mode':'cross_source','corpus_note':'Exactly three fictional documents supplied for deterministic mechanics tests.',
        'source_sufficiency_reason':'The fictional claim and presentation statements are inspectable; no claim of real-news completeness.',
        'selection_method':'Fixed synthetic test fixture, not a sample of real coverage.',
        'independence_check':'S1/S2 share an originating release; S3 supplies a separately described observation. These are fixture declarations.',
        'limitations':['Synthetic judgments are preassigned test inputs, not an evaluated detection method.','No real LLM review or web retrieval occurred.'],
        'material_gaps':[]}
    d['watchlist']=['Actual pilot protocol or field data would be needed before making a household-lifetime claim.',
                     'Real article access and a real independent review would be required for a real investigation.']
    d['review']={'mode':'independent','run_id':'synthetic-review-run-1','agent_id':'synthetic-review-context',
        'record_ref':'synthetic fixture only; no independent model call occurred','input_sha256':'',
        'completed_at':'2026-09-03T12:10:00Z','status':'accepted',
        'findings':[{'id':'R1','severity':'minor','issue':'Several dimensions reuse the same promotional observation.',
                    'resolved':True,'resolution':'Overlap groups and the absence of independent-proof claims are explicit in this synthetic fixture.'}]}
    return reseal(d)


if __name__ == '__main__':
    target=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'examples/synthetic_dossier.json'
    if target.exists():
        raise SystemExit(f'Refusing to overwrite existing fixture: {target}')
    target.write_text(json.dumps(make_fixture(),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(target)
