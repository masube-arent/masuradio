'use strict';
const assert = require('node:assert/strict');
const {createStore,createController,safeChapters} = require('../site/playback_state.js');
function storage() {
 const data=new Map();return {
  data,
  getItem(k){return data.has(k)?data.get(k):null},
  setItem(k,v){data.set(k,v)},removeItem(k){data.delete(k)}
 };
}
function player() {return {currentTime:0,readyState:1,playCount:0,pauseCount:0,
  play(){this.playCount++;return Promise.resolve()},pause(){this.pauseCount++},load(){this.currentTime=0}};}
const a={date:'2026-11-06',audio:'episodes/2026-11-06.mp3',duration_seconds:500,
 chapters:[{title:'ニュース',start_seconds:0},{title:'深掘り',start_seconds:140},{title:'まとめ',start_seconds:380}]};
const b={date:'2026-11-05',audio:'episodes/2026-11-05.mp3',duration_seconds:600};
{
 const audio=player(),store=storage();let time=10000;
 const app=createController(audio,store,{},()=>time);
 app.select(a);
 assert.equal(audio.playCount,0,'selection must not autoplay');
 audio.currentTime=75;app.persist();
 assert.equal(app.getResumePoint(),75);
 app.select(b);assert.equal(app.getResumePoint(),null,'another episode must not inherit position');
 app.select(a);assert.equal(app.resume(),true);
 assert.equal(audio.currentTime,75);assert.equal(audio.playCount,1);
 assert.equal(app.chapter(1),true);assert.equal(audio.currentTime,140);
 assert.equal(app.chapter(99),false);
 time+=6000;audio.currentTime=200;app.persist();
 assert.equal(app.getResumePoint(),200);
 assert.equal(app.startOver(),true);assert.equal(audio.currentTime,0);
 assert.equal(app.getResumePoint(),null,'start over clears saved state');
 audio.currentTime=30;app.persist(true);app.onEnded();
 assert.equal(app.getResumePoint(),null,'ended clears position');
 app.select(b);assert.deepEqual(app.getChapters(),[],'old episodes lack chapters');
 assert.equal(app.chapter(0),false);assert.equal(audio.playCount,2);
}
{
 const audio=player(),storageBlocked={getItem(){throw Error('private')},setItem(){throw Error('private')},removeItem(){throw Error('private')}};
 const app=createController(audio,storageBlocked);app.select(a);
 audio.currentTime=30;app.persist(true);assert.equal(app.resume(),false);
 assert.equal(app.startOver(),true);assert.equal(audio.playCount,1,'private mode still plays');
}
{
 const audio=player(),store=storage();const app=createController(audio,store);
 audio.readyState=0;app.select(a);assert.equal(app.chapter(2),true);
 assert.equal(audio.currentTime,0);audio.readyState=1;app.onMetadata();
 assert.equal(audio.currentTime,380,'chapter seeks after metadata loads');
}
{
 const s=createStore(storage());
 assert.equal(s.set('id',495,500),false,'never persist near-end position');
 assert.equal(s.set('id',20,500),true);assert.equal(s.get('id',500),20);
 s.clear('id');assert.equal(s.get('id',500),null);
 const chapters=safeChapters({...a,chapters:[{title:'A',start_seconds:10},{title:'B',start_seconds:10},{title:'C',start_seconds:900}]});
 assert.equal(chapters.length,1);
}
console.log('Playback tests passed');