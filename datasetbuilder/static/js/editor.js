/* DatasetBuilder structured Markdown studio. No editor content is executed as HTML. */
'use strict';
(() => {
  const root = document.getElementById('document-editor');
  if (!root) return;
  const $ = (sel, base=document) => base.querySelector(sel);
  const $$ = (sel, base=document) => [...base.querySelectorAll(sel)];
  const E = window.DB.escapeHTML;
  const t = window.DB.t;
  const data = JSON.parse($('#editor-data').textContent);
  const copy = obj => JSON.parse(JSON.stringify(obj));
  let docId = data.id;
  let revision = data.revision;
  let kbCode = data.kb;
  let parsed = copy(data.parsed);
  let sections = (parsed.sections || []).map(s => ({title:s.title, body:s.body || ''}));
  let solutions = (parsed.solutions || []).map(s => ({title:s.title, body:s.body || ''}));
  let activeTab = 'structured';
  let rawCodeMirror = null;
  let dirty = false;
  let saving = false;
  let previewTimer = null;
  let previewRequest = 0;
  let insertAfter = null;
  let cardEditors = [];
  const heading = $('#doc-title');
  const rawPanel = $('#raw-panel');
  const structuredPanel = $('#structured-panel');
  const modal = bootstrap.Modal.getOrCreateInstance($('#section-template-modal'));
  const conflictModal = bootstrap.Modal.getOrCreateInstance($('#conflict-modal'));
  const toolset = [
    ['bold','fa-bold',t('md_bold')], ['italic','fa-italic',t('md_italic')],
    ['heading','fa-heading',t('md_heading')], ['link','fa-link',t('md_link')],
    ['ul','fa-list-ul',t('md_bullet_list')], ['ol','fa-list-ol',t('md_numbered_list')],
    ['code','fa-code',t('md_inline_code')], ['codeblock','fa-laptop-code',t('md_code_block')],
    ['quote','fa-quote-left',t('md_quote')], ['table','fa-table',t('md_table')],
    ['undo','fa-rotate-left',t('md_undo')], ['redo','fa-rotate-right',t('md_redo')]
  ];

  const normalizeLines = value => String(value ?? '').replace(/\r\n?/g, '\n');
  const textField = (key, fallback='') => $('.meta-input[data-key="'+key+'"]')?.value || fallback;
  // Metadata comboboxes are <select>; make sure a value coming from the raw
  // Markdown that is not one of the options is still selectable.
  const setMetaValue = (input, value) => {
    if (input.tagName !== 'SELECT') { input.value = value; return; }
    if (value && ![...input.options].some(o => o.value === value)) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      input.appendChild(option);
    }
    input.value = value;
  };
  const metadataValues = () => {
    const obj = {...parsed.metadata};
    $$('.meta-input').forEach(input => obj[input.dataset.key] = input.value);
    return obj;
  };
  const buildMarkdown = () => {
    const title = heading.value.trim() || 'Untitled problem';
    const out = [`# ${kbCode}: ${title}`, ''];
    const metadata = metadataValues();
    const provenance = new Set(['Created By','Last Edited By','Revision','Created At','Updated At']);
    Object.entries(metadata).forEach(([key,value]) => {
      if (!provenance.has(key) && /^[A-Za-z][A-Za-z ]{1,50}$/.test(key))
        out.push(`${key}: ${String(value ?? '').replace(/\n/g, ' ').trim()}`);
    });
    out.push('');
    if (parsed.intro?.trim()) out.push(parsed.intro.trim(), '');
    let solutionsInserted = false;
    const insertSolutions = () => {
      if (!solutions.length || solutionsInserted) return;
      out.push('## SOLUTIONS', '');
      solutions.forEach((sol,i) => {
        out.push(`### Solution ${i+1}: ${(sol.title||'Untitled solution').replace(/[\r\n]/g,' ')}`, '', normalizeLines(sol.body).trim(), '');
      });
      solutionsInserted = true;
    };
    sections.forEach(sec => {
      const title = (sec.title || 'NEW SECTION').replace(/[\r\n]/g,' ').trim();
      // Keep solutions adjacent to corrective actions for predictable RAG ingestion.
      out.push(`## ${title}`, '', normalizeLines(sec.body).trim(), '');
      if (title.toUpperCase() === 'CORRECTIVE ACTIONS') insertSolutions();
    });
    insertSolutions();
    return out.join('\n').trimEnd() + '\n';
  };
  const getCurrentMarkdown = () => activeTab === 'raw' && rawCodeMirror ? rawCodeMirror.getValue() : buildMarkdown();

  function setDirty(value=true) {
    if (saving && value) return;
    dirty = value;
    const status = $('#save-indicator');
    status.classList.toggle('modified', dirty);
    status.innerHTML = `<span class="live-dot"></span> ${E(dirty?t('unsaved'):t('ready'))}`;
  }
  function changed() { setDirty(true); schedulePreview(); }
  function schedulePreview() {
    clearTimeout(previewTimer);
    $('#preview-status-label').textContent = t('preview_updating');
    previewTimer = setTimeout(runPreview, 350);
  }
  async function runPreview() {
    const seq = ++previewRequest;
    const markdown = getCurrentMarkdown();
    const count = (markdown.match(/\S+/gu) || []).length;
    $('#word-count').textContent = `${count} ${t('word_count')}`;
    try {
      const response = await window.DB.api('/api/preview', {method:'POST',body:JSON.stringify({markdown})});
      if (seq !== previewRequest) return;
      $('#markdown-preview').innerHTML = response.html;
      $('#preview-status-label').textContent = t('ready');
    } catch (error) {
      if (seq !== previewRequest) return;
      $('#preview-status-label').textContent = t('preview_failed');
      // Plain text only. Never insert unsanitized Markdown into the DOM.
      $('#markdown-preview').textContent = error.message;
    }
  }

  function applyEdit(cm, action) {
    if (action === 'undo' || action === 'redo') {cm[action]();return;}
    const selection = cm.getSelection();
    const multi = selection.includes('\n');
    const operators = {
      bold:['**','**','strong text'], italic:['*','*','emphasized text'],
      code:['`','`','code'], heading:['### ','','Heading'],
      link:['[','](https://example.com)','link text'], ul:['- ','','list item'],
      ol:['1. ','','list item'], quote:['> ','','quotation'],
      codeblock:['```\n','\n```','code here'],
      table:['\n| Column 1 | Column 2 |\n| --- | --- |\n| Value | Value |\n','',''],
    };
    const [before,after,placeholder] = operators[action] || ['', '', ''];
    cm.replaceSelection(before+(selection||placeholder)+after, 'around');
    cm.focus();
    if (!selection && placeholder && !multi) {
      const cursor = cm.getCursor();
      const end = {...cursor, ch:cursor.ch-after.length};
      const start = {...end, ch:end.ch-placeholder.length};
      if (start.ch >= 0) cm.setSelection(start,end);
    }
  }

  function mkIconButton(icon, title, action, disabled=false) {
    return `<button type="button" class="block-action" data-action="${action}" title="${E(title)}" aria-label="${E(title)}" ${disabled?'disabled':''}><i class="fa-solid ${icon}"></i></button>`;
  }
  function renderCard(entry, index, type) {
    const isSolution = type === 'solution';
    const label = isSolution ? `S${index+1}` : String(index+1).padStart(2,'0');
    const bodyId = `${type}-body-${index}`;
    const options = toolset.map(([action,icon,label]) => `<button class="md-action" type="button" data-md="${action}" title="${E(label)}" aria-label="${E(label)}"><i class="fa-solid ${icon}"></i></button>`).join('');
    const wrapper = document.createElement('div');
    wrapper.className = 'editing-section block-card' + (isSolution ? ' solution-card' : '');
    wrapper.dataset.kind = type;
    wrapper.dataset.index = index;
    wrapper.id = `${type}-block-${index}`;
    wrapper.innerHTML = `<div class="block-headline"><span class="block-number">${label}</span><div class="block-title-wrap"><label class="block-label" for="${type}-title-${index}">${E(isSolution?t('solution_title'):t('section_name'))}</label><input id="${type}-title-${index}" class="form-control section-heading-input" maxlength="120" value="${E(entry.title)}"></div><div class="block-controls">${!isSolution?mkIconButton('fa-circle-plus',t('add_subsection'),'subsection'):''}${mkIconButton('fa-arrow-up',t('move_up'),'up',index===0)}${mkIconButton('fa-arrow-down',t('move_down'),'down',index===(isSolution?solutions:sections).length-1)}${mkIconButton('fa-trash',t(isSolution?'delete_solution_button':'delete_section_button'),'remove')}</div></div><div class="md-toolbar" role="toolbar" aria-label="${E(t('markdown_toolbar'))}">${options}</div><div class="md-editor-wrap"><textarea id="${bodyId}" class="md-input" placeholder="${E(t(isSolution?'solution_content':'section_content'))}"></textarea></div><div class="block-foot"><span><i class="fa-brands fa-markdown me-2"></i>${E(t('markdown_tip'))}</span><span>${E(isSolution?t('solution_label'):t('section_label'))}</span></div>`;
    const input = $('.section-heading-input',wrapper);
    input.addEventListener('input',e=>{ entry.title=e.target.value; refreshNav();changed(); });
    $$('.block-action',wrapper).forEach(btn=>btn.addEventListener('click',() => mutate(type,index,btn.dataset.action)));
    const textarea = $('.md-input',wrapper);
    textarea.value = entry.body;
    const cm = CodeMirror.fromTextArea(textarea, {
      mode:'gfm',theme:'default',lineNumbers:false,lineWrapping:true,
      viewportMargin:12,indentUnit:2,tabSize:2,indentWithTabs:false,
      autoCloseBrackets:true,extraKeys:{'Enter':'newlineAndIndentContinueMarkdownList','Ctrl-B':cm=>applyEdit(cm,'bold'),'Cmd-B':cm=>applyEdit(cm,'bold'),'Ctrl-I':cm=>applyEdit(cm,'italic'),'Cmd-I':cm=>applyEdit(cm,'italic')}
    });
    cm.setSize(null,'auto');
    cardEditors.push(cm);
    cm.on('change',()=>{entry.body=cm.getValue();changed();});
    cm.on('focus',()=>markSelected(type,index));
    $$('.md-action',wrapper).forEach(btn=>btn.addEventListener('click',()=>applyEdit(cm,btn.dataset.md)));
    return wrapper;
  }
  function markSelected(type,index) {
    $$('.outline-item').forEach(item=>item.classList.toggle('selected',item.dataset.kind===type && +item.dataset.index===index));
  }
  function refreshNav() {
    const sectionsNav = $('#section-nav'),solutionsNav = $('#solution-nav');
    sectionsNav.innerHTML = sections.map((section,i) => `<button type="button" class="outline-item" data-kind="section" data-index="${i}"><span class="outline-n">${String(i+1).padStart(2,'0')}</span><span>${E(section.title||t('untitled'))}</span></button>`).join('');
    solutionsNav.innerHTML = solutions.map((solution,i) => `<button type="button" class="outline-item" data-kind="solution" data-index="${i}"><span class="outline-n solution-n">S${i+1}</span><span>${E(solution.title||t('untitled'))}</span></button>`).join('');
    $$('.outline-item').forEach(button=>button.addEventListener('click',()=>{
      $(`#${button.dataset.kind}-block-${button.dataset.index}`)?.scrollIntoView({behavior:'smooth',block:'center'});
      markSelected(button.dataset.kind,+button.dataset.index);
    }));
  }
  function renderBlocks() {
    const secContainer = $('#sections-container'), solContainer = $('#solutions-container');
    cardEditors.forEach(cm=>cm.toTextArea());
    cardEditors=[];
    secContainer.textContent='';solContainer.textContent='';
    sections.forEach((section,i)=>{
      secContainer.append(renderCard(section,i,'section'));
      const insert = document.createElement('div');
      insert.className='insert-between';
      insert.innerHTML=`<button class="btn btn-insert" type="button" title="${E(t('add_after'))}"><i class="fa-solid fa-circle-plus"></i></button>`;
      insert.querySelector('button').addEventListener('click',()=>showSectionPicker(i));
      secContainer.append(insert);
    });
    solutions.forEach((solution,i)=>solContainer.append(renderCard(solution,i,'solution')));
    if(!solutions.length)solContainer.innerHTML=`<div class="no-solutions"><i class="fa-solid fa-lightbulb me-2"></i>${E(t('empty_solution'))}</div>`;
    refreshNav();
    // CodeMirror needs refresh after the DOM nodes have been connected.
    setTimeout(()=>cardEditors.forEach(cm=>cm.refresh()),20);
  }
  function mutate(type,index,action) {
    const arr = type==='solution'?solutions:sections;
    if (action==='subsection') {
      arr[index].body += (arr[index].body.endsWith('\n')?'':'\n')+'\n### New subsection\n\n';
      renderBlocks();changed();window.toastr.info(t('add_subsection'));
      return;
    }
    if (action==='remove') {
      if(!confirm(t(type==='solution'?'delete_solution':'delete_section'))) return;
      arr.splice(index,1);
      window.toastr.info(type==='solution'?t('delete_solution_button'):t('delete_section_button'));
    } else if(action==='up' && index>0) {
      [arr[index],arr[index-1]]=[arr[index-1],arr[index]];
    } else if(action==='down' && index<arr.length-1) {
      [arr[index],arr[index+1]]=[arr[index+1],arr[index]];
    } else return;
    renderBlocks();changed();
    if(action!=='remove')window.toastr.info(t('moved_section'));
  }
  function showSectionPicker(index=null) {insertAfter=index;modal.show();}
  function addSection(title) {
    const at = insertAfter===null ? sections.length : insertAfter+1;
    sections.splice(at,0,{title,body:''});
    modal.hide();renderBlocks();changed();
    $(`#section-block-${at}`)?.scrollIntoView({behavior:'smooth',block:'center'});
    $(`#section-block-${at} .section-heading-input`)?.focus();
    window.toastr.success(t('add_section'));
  }
  function addSolution() {
    const at=solutions.length;
    solutions.push({title:`${t('solution_title')} ${at+1}`,body:'**Prerequisites:**\n\n**Resolution steps:**\n\n1. \n\n**Expected result:**\n'});
    renderBlocks();changed();
    $(`#solution-block-${at}`)?.scrollIntoView({behavior:'smooth',block:'center'});
    window.toastr.success(t('add_solution'));
  }
  $$('.template-choice').forEach(button=>button.addEventListener('click',()=>addSection(button.dataset.section)));
  $('#nav-add-section').addEventListener('click',()=>showSectionPicker());
  $('#content-add-section').addEventListener('click',()=>showSectionPicker());
  $('#nav-add-solution').addEventListener('click',addSolution);
  $('#content-add-solution').addEventListener('click',addSolution);

  async function toStructured() {
    try {
      const result = await window.DB.api('/api/parse',{method:'POST',body:JSON.stringify({markdown:rawCodeMirror.getValue()})});
      parsed = result.parsed;
      sections = (parsed.sections||[]).map(s=>({title:s.title,body:s.body||''}));
      solutions = (parsed.solutions||[]).map(s=>({title:s.title,body:s.body||''}));
      $('.meta-input') && $$('.meta-input').forEach(input=>setMetaValue(input,parsed.metadata?.[input.dataset.key]||''));
      activeTab='structured';rawPanel.classList.add('d-none');structuredPanel.classList.remove('d-none');
      $('#mode-toggle span').textContent=t('raw');
      $('#mode-toggle i').className='fa-solid fa-code me-2';
      renderBlocks();schedulePreview();
    }catch(error){window.toastr.error(error.message);}
  }
  function toRaw() {
    const code=buildMarkdown();
    activeTab='raw';rawPanel.classList.remove('d-none');structuredPanel.classList.add('d-none');
    $('#mode-toggle span').textContent=t('structured');
    $('#mode-toggle i').className='fa-solid fa-layer-group me-2';
    if(!rawCodeMirror) {
      rawCodeMirror=CodeMirror.fromTextArea($('#raw-editor'), {mode:'gfm',lineNumbers:true,lineWrapping:true,indentUnit:2,autoCloseBrackets:true,extraKeys:{'Enter':'newlineAndIndentContinueMarkdownList'}});
      rawCodeMirror.setSize(null, '70vh');
      rawCodeMirror.on('change',changed);
    }
    rawCodeMirror.setValue(code);
    setTimeout(()=>rawCodeMirror.refresh(),60);
    schedulePreview();
  }
  $('#mode-toggle').addEventListener('click',()=>activeTab==='raw'?toStructured():toRaw());
  heading.addEventListener('input',changed);
  $$('.meta-input').forEach(input=>{input.addEventListener('input',changed);input.addEventListener('change',changed);});
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});

  async function save() {
    if(saving)return;
    const title=heading.value.trim();
    if(title.length<3){window.toastr.error(t('title_min'));heading.focus();return;}
    const markdown=getCurrentMarkdown();
    saving=true;
    const button=$('#save-document');button.disabled=true;
    try {
      const created=!docId;
      const url=created?'/api/documents':`/api/documents/${docId}`;
      const result=await window.DB.api(url,{
        method:created?'POST':'PUT',
        body:JSON.stringify({title,markdown,revision,note:$('#revision-note').value.trim()})
      });
      docId=result.document.id;revision=result.document.revision;kbCode=result.document.kb_id;
      root.dataset.id=String(docId);root.dataset.revision=String(revision);
      dirty=false;
      $('#revision-note').value='';
      setDirty(false);
      window.toastr.success(created?t('file_created'):t('file_saved'));
      if(result.document.sync_error)window.toastr.warning(t('file_sync_problem'));
      if(created){ location.assign(result.redirect); return; }
      $('.code-tag',root).textContent=kbCode;
      if(activeTab==='raw') {
        const saved=rawCodeMirror.getValue().replace(/^#\s+.*$/m,`# ${kbCode}: ${title}`);
        rawCodeMirror.setValue(saved);
      }
      schedulePreview();
    }catch(error){
      if(error.status===409){conflictModal.show();window.toastr.warning(t('conflict'));}
      else window.toastr.error(error.message);
    }finally{ saving=false;button.disabled=false; }
  }
  $('#save-document').addEventListener('click',save);
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();save();}});
  $('#copy-unsaved').addEventListener('click',async()=>{
    try{await navigator.clipboard.writeText(getCurrentMarkdown());window.toastr.success(t('copied'));}catch(error){window.toastr.error(error.message);}
  });
  $('#download-unsaved').addEventListener('click',()=>{
    const blob=new Blob([getCurrentMarkdown()],{type:'text/markdown;charset=utf-8'});
    const url=URL.createObjectURL(blob);const a=document.createElement('a');
    a.href=url;a.download=`${kbCode}-unsaved.md`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    window.toastr.info(t('markdown_draft_downloaded'));
  });
  $('#reload-latest').addEventListener('click',()=>{dirty=false;location.reload();});
  renderBlocks();setDirty(false);schedulePreview();
})();
