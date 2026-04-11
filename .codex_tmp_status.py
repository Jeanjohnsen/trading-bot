import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/settings', timeout=5) as r:
    settings = json.load(r)
with urllib.request.urlopen('http://127.0.0.1:8000/opportunities', timeout=5) as r:
    opps = json.load(r)
approved = [o for o in opps if o.get('status') == 'approved']
research = [o for o in approved if o.get('strategy_type') == 'research_signal']
print(json.dumps({
  'mode': settings['current_mode'],
  'research_mode': settings['app']['enable_research_mode'],
  'live_trading': settings['app']['enable_live_trading'],
  'using_demo_data': settings['using_demo_data'],
  'approved_total': len(approved),
  'approved_research_signal': len(research)
}, indent=2))
