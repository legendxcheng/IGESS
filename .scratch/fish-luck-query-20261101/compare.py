"""Exact business comparisons; only explicitly named identity metadata is ignored."""
from pathlib import Path
import base64, copy, json, sys, zlib
CORE=('timeline.json','events.json','source_progression.json','source_behavior.json')
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def normalized_checkpoint(checkpoint):
    value=copy.deepcopy(checkpoint)
    value.pop('model_digest')
    packed=value.pop('engine_state');assert packed['codec']=='zlib-json-v1'
    session=json.loads(zlib.decompress(base64.b64decode(packed['data'])))
    session.pop('codeDigest')
    return value,session
def compare(first,second):
    receipts=[read(first),read(second)]
    assert all(r['response']['ok'] and r['response']['result']['status']=='success' for r in receipts)
    outputs=[Path(r['response']['result']['output_dir']) for r in receipts]
    for name in CORE:
        assert (outputs[0]/name).read_bytes()==(outputs[1]/name).read_bytes(),name
    checkpoints=[normalized_checkpoint(read(p/'final_checkpoint.json')) for p in outputs]
    assert checkpoints[0]==checkpoints[1], 'checkpoint behavior or ordered source history differs'
    manifests=[read(p/'run_manifest.json') for p in outputs]
    for manifest in manifests:
        manifest.pop('model_digest')
        for key in ('code_sha256','timings_seconds'):
            manifest['source_runtime'].pop(key)
    assert manifests[0]==manifests[1], 'manifest input or business metadata differs'
    if receipts[0]['diagnostic_only']:
        assert receipts[1]['diagnostic_only']
        assert receipts[0]['observation_trace']==receipts[1]['observation_trace'], 'logical query trace differs'
        assert read(receipts[0]['final_observation'])==read(receipts[1]['final_observation']), 'full final state differs'
    # A negative control for the checkpoint comparator must detect a business mutation.
    tampered=read(outputs[0]/'final_checkpoint.json')
    tampered['next_throw_id']+=1
    assert normalized_checkpoint(tampered)!=checkpoints[0], 'negative control failed'
    return dict(first=str(first),second=str(second),core_bytes_identical=True,
        checkpoint_and_ordered_history_identical=True,negative_control_rejected=True,
        observations=len(receipts[0].get('observation_trace',[])),
        seconds=[r['timings']['total'] for r in receipts])
if __name__=='__main__':print(json.dumps(compare(*sys.argv[1:]),indent=2))
