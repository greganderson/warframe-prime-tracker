import type {VoiceMessage} from './types';

// Collects ~0.1 s of mono samples per message so the socket isn't flooded with 128-sample frames.
const worklet=`class Capture extends AudioWorkletProcessor{constructor(){super();this.buffer=[];this.size=0}
process(inputs){const channel=inputs[0][0];if(channel){this.buffer.push(channel.slice());this.size+=channel.length;
if(this.size>=sampleRate/10){const out=new Float32Array(this.size);let offset=0;for(const part of this.buffer){out.set(part,offset);offset+=part.length}
this.port.postMessage(out,[out.buffer]);this.buffer=[];this.size=0}}return true}}registerProcessor('capture',Capture)`;

export const voiceSupported=()=>!!navigator.mediaDevices?.getUserMedia&&typeof AudioWorkletNode!=='undefined';

/** Streams the microphone to the backend recognizer. Call the returned stop() to get the final result. */
export async function startDictation(era:string|null,onMessage:(message:VoiceMessage)=>void):Promise<()=>void>{
 const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
 const context=new AudioContext();
 const cleanup=()=>{stream.getTracks().forEach(track=>track.stop());void context.close()};
 try{
  const url=URL.createObjectURL(new Blob([worklet],{type:'application/javascript'}));
  await context.audioWorklet.addModule(url);URL.revokeObjectURL(url);
  const params=new URLSearchParams({rate:String(context.sampleRate),...(era?{era}:{})});
  const socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/v1/voice?${params}`);
  socket.binaryType='arraybuffer';
  const node=new AudioWorkletNode(context,'capture');
  node.port.onmessage=({data}:MessageEvent<Float32Array>)=>{
   if(socket.readyState!==WebSocket.OPEN)return;
   const pcm=new Int16Array(data.length);
   for(let i=0;i<data.length;i++)pcm[i]=Math.max(-1,Math.min(1,data[i]))*0x7fff;
   socket.send(pcm.buffer);
  };
  context.createMediaStreamSource(stream).connect(node);
  socket.onmessage=event=>onMessage(JSON.parse(event.data));
  socket.onerror=()=>onMessage({error:'Voice connection failed'});
  socket.onclose=cleanup;
  return ()=>{node.port.onmessage=null;if(socket.readyState===WebSocket.OPEN)socket.send('stop');else cleanup()};
 }catch(error){cleanup();throw error}
}
