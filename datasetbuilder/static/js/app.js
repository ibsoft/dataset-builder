'use strict';
(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];
  const csrf = $('meta[name="csrf-token"]')?.content || '';
  const i18n = JSON.parse($('#db-strings')?.textContent || '{}');
  const translations = i18n;
  const escapeHTML = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icons = {success:'fa-circle-check',error:'fa-circle-xmark',warning:'fa-triangle-exclamation',info:'fa-circle-info'};
  const toast = (level, msg) => {
    const parent = $('#toast-container'); if (!parent) return;
    const el = document.createElement('div');
    el.className = `toast toast-${level} fade`;
    el.setAttribute('role','status');el.setAttribute('aria-live','polite');
    el.innerHTML = `<div class="toast-header"><i class="fa-solid ${icons[level]||icons.info}"></i><strong class="me-auto">DatasetBuilder</strong><button class="btn-close" type="button" data-bs-dismiss="toast" aria-label="Close"></button></div><div class="toast-body">${escapeHTML(msg)}</div>`;
    parent.append(el);
    const inst = new bootstrap.Toast(el,{delay:4500});el.addEventListener('hidden.bs.toast',()=>el.remove());inst.show();
  };
  window.toastr = {success:m=>toast('success',m),error:m=>toast('error',m),warning:m=>toast('warning',m),info:m=>toast('info',m)};
  const deleteModalElement = $('#delete-confirm-modal');
  const deleteModal = bootstrap.Modal.getOrCreateInstance(deleteModalElement);
  let pendingDelete = null;
  let deleteAccepted = false;
  let deleteTrigger = null;
  deleteModalElement.addEventListener('shown.bs.modal',()=>$('#delete-confirm-cancel').focus());
  $('#delete-confirm-accept').addEventListener('click',()=>{deleteAccepted=true;deleteModal.hide();});
  deleteModalElement.addEventListener('hidden.bs.modal',()=>{
    const resolve = pendingDelete;
    pendingDelete = null;
    if(deleteTrigger?.isConnected)deleteTrigger.focus();
    deleteTrigger = null;
    if(resolve)resolve(deleteAccepted);
  });
  const confirmDelete = (message) => {
    if(pendingDelete)return Promise.resolve(false);
    deleteAccepted = false;
    deleteTrigger = document.activeElement;
    $('#delete-confirm-message').textContent = message;
    return new Promise(resolve=>{pendingDelete=resolve;deleteModal.show();});
  };
  window.DB = {csrf, t:(k)=>translations[k]||k, escapeHTML, toast, confirmDelete, async api(url, options={}) {
    const response = await fetch(url,{...options,headers:{'Content-Type':'application/json','X-CSRFToken':csrf,...(options.headers||{})},credentials:'same-origin'});
    let result;try{result=await response.json()}catch{result={error:`HTTP ${response.status}`}}
    if (!response.ok) {const e = new Error(result.error || `HTTP ${response.status}`);e.status=response.status;e.data=result;throw e;}
    return result;
  }};
  JSON.parse($('#db-flashes')?.textContent || '[]').forEach(([cat,msg])=>toast(cat==='message'?'info':cat,msg));
  $('#import-document')?.addEventListener('change',e=>{if(e.target.files.length){toast('info',translations.importing_markdown||'Importing UTF-8 Markdown…');e.target.form.submit()}});
  // Language switcher. Bound here rather than with an inline onchange handler,
  // which the Content-Security-Policy (script-src 'self') blocks.
  $$('.lang-switch').forEach(select=>select.addEventListener('change',()=>select.form?.submit()));
  $('#sidebar-toggle')?.addEventListener('click',()=>$('#appSidebar')?.classList.toggle('sidebar-open'));
  // Collapsible navigation. The collapsed state is stored in a cookie so the
  // server can render the rail at its final width on the first paint; applying
  // it here as well would animate the sidebar on every navigation.
  const NAV_COOKIE='datasetbuilder_nav';
  const navCollapse=$('#nav-collapse');
  const navCollapsed=()=>document.body.classList.contains('nav-collapsed');
  const setNavCookie=(collapsed)=>{
    const secure=location.protocol==='https:'?'; secure':'';
    document.cookie=`${NAV_COOKIE}=${collapsed?'collapsed':'expanded'}; path=/; max-age=31536000; samesite=Lax${secure}`;
  };
  const applyNav=(collapsed)=>{
    document.body.classList.toggle('nav-collapsed',collapsed);
    navCollapse?.setAttribute('aria-expanded',String(!collapsed));
    const label=collapsed?(translations.expand_nav||'Expand navigation'):(translations.collapse_nav||'Collapse navigation');
    if(navCollapse){navCollapse.title=label;navCollapse.setAttribute('aria-label',label);}
  };
  applyNav(navCollapsed());
  navCollapse?.addEventListener('click',()=>{const next=!navCollapsed();applyNav(next);setNavCookie(next);});
  document.querySelectorAll('[data-confirm]').forEach(form=>form.addEventListener('submit',e=>{if(!confirm(form.dataset.confirm))e.preventDefault()}));
  document.querySelectorAll('[data-confirm-delete]').forEach(form=>form.addEventListener('submit',async e=>{
    e.preventDefault();
    if(await confirmDelete(form.dataset.confirmDelete))form.submit();
  }));
  document.querySelectorAll('#nav-export,.btn[href="/export"]').forEach(a=>a.addEventListener('click',()=>toast('info',translations.preparing_export||'Preparing UTF-8 ZIP export…')));
  $('#print-document')?.addEventListener('click',()=>window.print());
  // Theme switch. The theme is stored per account (and in a cookie so it also
  // applies on the login screen), so it is posted to the server.
  const applyTheme=(theme)=>{
    document.documentElement.setAttribute('data-theme',theme);
    const icon=$('#theme-toggle')?.querySelector('i');
    if(icon)icon.className=`fa-solid fa-${theme==='dark'?'sun':'moon'}`;
  };
  $('#theme-toggle')?.addEventListener('click',async()=>{
    const button=$('#theme-toggle');
    const next=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
    button.disabled=true;
    try{
      const response=await fetch('/theme',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','X-CSRFToken':csrf},credentials:'same-origin',body:new URLSearchParams({theme:next,next:location.pathname+location.search})});
      if(response.ok)applyTheme(next);
    }catch(error){toast('error',error.message);}
    finally{button.disabled=false;}
  });
  $('#delete-document')?.addEventListener('click',async(event)=>{
    const btn = event.currentTarget;
    if(!await confirmDelete(translations.confirm_delete||'Move this article to trash?'))return;
    btn.disabled = true;
    try {const result=await window.DB.api(`/api/documents/${btn.dataset.id}`,{method:'DELETE',body:JSON.stringify({revision:Number(btn.dataset.revision)})});toast('success',translations.file_deleted||'Moved to trash');setTimeout(()=>location.assign(result.redirect),800)}
    catch(err){toast('error',err.message);btn.disabled=false;}
  });
})();
