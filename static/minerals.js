document.addEventListener('DOMContentLoaded', function(){
  document.querySelectorAll('.mineral-desc').forEach(function(container){
    const content = container.querySelector('.desc-content');
    const btn = container.querySelector('.desc-toggle');
    if(!content || !btn) return;
    // limit to around 3 lines via CSS; the JS manages toggle
    btn.addEventListener('click', function(){
      const expanded = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', expanded ? 'false' : 'true');
      btn.textContent = expanded ? 'Read more' : 'Show less';
      container.classList.toggle('expanded', !expanded);
    });
  });
});
