// Existing walkthrough tests start on the walkthrough page; replaceState avoids a stray hashchange.
beforeEach(() => {
  window.history.replaceState(null, '', '#/lineage')
})
