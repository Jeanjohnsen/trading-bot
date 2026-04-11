import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/settings', timeout=5) as r:
    settings = json.load(r)
with urllib.request.urlopen('http://127.0.0.1:8000/opportunities', timeout=5) as r:
    opps = json.load(r)
approved = [o for o in opps if o.get('status') == 'approved']
print(json.dumps({
  'mode': settings['current_mode'],
  'research': settings['app']['enable_research_mode'],
  'live_trading': settings['app']['enable_live_trading'],
  'using_demo_data': settings['using_demo_data'],
  'total_opportunities': len(opps),
  'approved_opportunities': len(approved),
  'first_strategy': approved[0]['strategy_type'] if approved else None,
  'first_question': approved[0]['question'] if approved else None
}, indent=2))
