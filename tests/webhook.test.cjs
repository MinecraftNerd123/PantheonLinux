'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8');

test('RunSettings implements Discord Components V2 structure and URL formatting',()=>{
  const py=read('pantheon/run_settings.py');
  for(const s of ['32768','with_components=true','"type": 17','"type": 10','"type": 14','"type": 1}','"type": 2','"style": 5','allowed_mentions','def test_webhook','def dispatch'])assert.ok(py.includes(s),s);
  const app=read('pantheon/app.py');
  assert.ok(app.includes('action == "dispatchWebhook"'));
  assert.ok(app.includes('action == "testWebhook"'));
});

test('run settings schema defines all supported event webhook and ping toggles',()=>{
  const schema=JSON.parse(read('Lib/ui/run-settings-schema.json'));
  const events=['Completed','Loss','Disconnect','Reconnect','Stopping','Shop'];
  for(const ev of events){
    assert.ok(schema.general.some(f=>f.key==='Webhook'+ev+'E'&&f.type==='toggle'&&f.eventType==='webhook'));
    assert.ok(schema.general.some(f=>f.key==='Ping'+ev+'E'&&f.type==='toggle'&&f.eventType==='ping'));
  }
});
