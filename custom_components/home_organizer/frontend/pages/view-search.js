// pages/view-search.js
// [ADDED v10.0.4] Search View

export const SearchMixin = (Base) => class extends Base {
  renderSearchView(content, attrs) {
      const list = document.createElement('div'); 
      list.className = 'item-list';
      if (attrs.items && attrs.items.length > 0) {
          attrs.items.forEach(item => {
              if (typeof this.createItemRow === 'function') {
                  list.appendChild(this.createItemRow(item, false));
              }
          });
      } else {
          list.innerHTML = `<div style="text-align:center;padding:20px;color:#888;">${this._t('no_results', 'No results found.')}</div>`;
      }
      content.appendChild(list);
  }
};