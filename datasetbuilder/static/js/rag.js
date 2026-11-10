'use strict';
(() => {
  const element = document.getElementById('rag-modal');
  const modal = bootstrap.Modal.getOrCreateInstance(element);
  if (location.hash === '#rag') modal.show();

  const upload = document.querySelector('[data-rag-upload]');
  upload?.addEventListener('submit', () => {
    document.getElementById('rag-upload-progress').classList.remove('d-none');
    upload.querySelector('button').disabled = true;
  });
  const refresh = document.querySelector('[data-rag-refresh]');
  let timer;
  element.addEventListener('shown.bs.modal', () => {
    if (refresh) timer = setTimeout(() => refresh.requestSubmit(), 5000);
  });
  element.addEventListener('hide.bs.modal', () => clearTimeout(timer));

  document.querySelector('[data-rag-confirm]')?.addEventListener('submit', event => {
    event.preventDefault();
    const form = event.currentTarget;
    element.addEventListener('hidden.bs.modal', async () => {
      if (await window.DB.confirmDelete(form.dataset.ragConfirm, form.dataset.confirmTitle, form.dataset.confirmAction)) {
        form.submit();
      } else {
        modal.show();
      }
    }, {once: true});
    modal.hide();
  });
})();
