async function postJSON(url, data){
  const res = await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  const body = await res.json();
  if(!res.ok) throw new Error(body.error || "Request failed");
  return body;
}

const bmiBtn=document.getElementById("bmiBtn");
if(bmiBtn){
  bmiBtn.addEventListener("click",async()=>{
    const height=document.getElementById("height").value;
    const weight=document.getElementById("weight").value;
    const result=document.getElementById("bmiResult");
    try{
      const data=await postJSON("/api/bmi",{height,weight});
      result.innerHTML=`<strong>BMI: ${data.bmi}</strong> — ${data.category}`;
      const dash=document.getElementById("dash-bmi"); if(dash) dash.textContent=data.bmi;
    }catch(e){result.textContent=e.message}
  });
}

const workoutBtn=document.getElementById("workoutBtn");
if(workoutBtn){
  workoutBtn.addEventListener("click",async()=>{
    const goal=document.getElementById("workoutGoal").value;
    const result=document.getElementById("workoutResult");
    try{
      const data=await postJSON("/api/workout",{goal});
      result.innerHTML=data.plan.map(x=>`<div><b>${x[0]} — ${x[1]}</b><br><small>${x[2]}</small></div>`).join("<hr>");
    }catch(e){result.textContent=e.message}
  });
}

const dietBtn=document.getElementById("dietBtn");
if(dietBtn){
  dietBtn.addEventListener("click",async()=>{
    const goal=document.getElementById("dietGoal").value;
    const result=document.getElementById("dietResult");
    try{
      const data=await postJSON("/api/diet",{goal});
      result.innerHTML=`<strong>${data.calories} kcal/day</strong><br>${data.meals}`;
    }catch(e){result.textContent=e.message}
  });
}

// Keep the user's scroll position after saving forms on long Admin/Member pages.
// This is especially useful when a form is near the middle or bottom of the page.
(function preserveScrollPosition(){
  const restorePaths = ["/admin", "/dashboard"];
  if(!restorePaths.includes(window.location.pathname)) return;

  const key = `oxyzon-scroll:${window.location.pathname}`;
  if("scrollRestoration" in history) history.scrollRestoration = "manual";

  const samePageReferrer = (() => {
    try {
      return document.referrer && new URL(document.referrer).pathname === window.location.pathname;
    } catch(e) {
      return false;
    }
  })();

  const restore = () => {
    const saved = sessionStorage.getItem(key);
    if(!samePageReferrer || saved === null) return;
    const y = Number(saved);
    if(Number.isFinite(y)){
      requestAnimationFrame(() => {
        window.scrollTo(0, y);
        setTimeout(() => window.scrollTo(0, y), 80);
      });
    }
  };
  restore();
  window.addEventListener("pageshow", restore);

  const saveScroll = () => {
    sessionStorage.setItem(key, String(window.scrollY || window.pageYOffset || 0));
  };

  window.addEventListener("pagehide", saveScroll);
  window.addEventListener("beforeunload", saveScroll);
})();
