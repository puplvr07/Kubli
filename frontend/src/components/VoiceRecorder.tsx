import { useEffect, useRef, useState } from 'react'
import { Mic, Square, LoaderCircle } from 'lucide-react'
import { api } from '../api'
export default function VoiceRecorder({disabled,onTranscript,onError}: {disabled:boolean;onTranscript:(text:string)=>void;onError:(error:unknown)=>void}) {
  const [recording,setRecording]=useState(false);const [transcribing,setTranscribing]=useState(false)
  const [seconds,setSeconds]=useState(0);const [level,setLevel]=useState(0);const [notice,setNotice]=useState('')
  const recorder=useRef<MediaRecorder|null>(null);const stream=useRef<MediaStream|null>(null)
  const context=useRef<AudioContext|null>(null);const frame=useRef(0);const chunks=useRef<Blob[]>([])
  const cancelled=useRef(false);const timer=useRef<ReturnType<typeof setInterval>|undefined>(undefined)
  function cleanup(){stream.current?.getTracks().forEach(track=>track.stop());stream.current=null;cancelAnimationFrame(frame.current);clearInterval(timer.current);void context.current?.close().catch(()=>{});context.current=null}
  useEffect(()=>()=>{cancelled.current=true;if(recorder.current?.state==='recording')recorder.current.stop();cleanup()},[])
  async function start(){
    cancelled.current=false;setNotice('')
    try{
      if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Audio capture is not supported here. Use an up-to-date browser at http://127.0.0.1:5173 or type the encounter.')
      const mic=await navigator.mediaDevices.getUserMedia({audio:true});stream.current=mic
      if(cancelled.current){cleanup();return}
      const mime=['audio/webm;codecs=opus','audio/mp4','audio/webm'].find(type=>MediaRecorder.isTypeSupported(type))
      recorder.current=new MediaRecorder(mic,mime?{mimeType:mime}:{});chunks.current=[]
      recorder.current.ondataavailable=event=>{if(event.data.size)chunks.current.push(event.data)}
      recorder.current.onstop=async()=>{
        setRecording(false);setLevel(0);cleanup()
        if(cancelled.current){chunks.current=[];return}
        const blob=new Blob(chunks.current,{type:recorder.current?.mimeType||'audio/webm'});chunks.current=[]
        setTranscribing(true)
        try{
          const form=new FormData();form.append('audio',blob,'dictation.webm')
          const result=await api<{text:string;language:string;notice:string}>('/api/transcribe',{method:'POST',body:form})
          if(!cancelled.current){onTranscript(result.text);setNotice(`Detected ${result.language}. ${result.notice}`)}
        }catch(e){if(!cancelled.current)onError(e)}finally{if(!cancelled.current)setTranscribing(false)}
      }
      recorder.current.onerror=()=>{cancelled.current=true;cleanup();setRecording(false);onError(new Error('Microphone recording failed. Check the browser permission and try again, or type the encounter.'))}
      context.current=new AudioContext();const source=context.current.createMediaStreamSource(mic);const analyser=context.current.createAnalyser();analyser.fftSize=256;source.connect(analyser)
      const values=new Uint8Array(analyser.frequencyBinCount)
      function meter(){analyser.getByteTimeDomainData(values);const rms=Math.sqrt(values.reduce((sum,x)=>sum+(x-128)**2,0)/values.length)/128;setLevel(Math.min(100,rms*350));frame.current=requestAnimationFrame(meter)}
      meter();setSeconds(0);setRecording(true);recorder.current.start()
      let elapsed=0;timer.current=setInterval(()=>{elapsed++;setSeconds(elapsed);if(elapsed>=120&&recorder.current?.state==='recording')recorder.current.stop()},1000)
    }catch(e){cleanup();setRecording(false);const name=(e as DOMException).name;onError(new Error(name==='NotAllowedError'?'Microphone permission denied. Allow the microphone for 127.0.0.1 in browser settings, or type the encounter.':name==='NotFoundError'?'No microphone found. Type the encounter or enable Demo mode.':(e as Error).message))}
  }
  return <div className="mb-4"><div className="flex gap-3 items-center"><button className={recording?'btn !border-rose-200 !text-rose-800':'btn !text-xs'} disabled={disabled||transcribing} onClick={()=>recording?recorder.current?.stop():void start()}>{transcribing?<LoaderCircle size={14} className="animate-spin"/>:recording?<Square size={14}/>:<Mic size={14}/>} {transcribing?'Transcribing locally…':recording?`Stop · ${seconds}s`:'Dictate encounter'}</button>{recording&&<div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden" role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level)}><div className="h-full bg-teal-500 rounded-full" style={{width:`${level}%`}}/></div>}</div>{notice&&<p className="text-[10px] text-slate-500 mt-2 leading-relaxed">{notice}</p>}{recording&&<p className="text-[10px] text-rose-700 mt-2">Recording locally · maximum 2 minutes. Stop to transcribe.</p>}</div>
}
