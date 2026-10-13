export function fuzzyMatch(row, query) {
  const normalize = value => String(value || '').normalize('NFKD').toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
  const needle = normalize(query);
  return ['name', 'code', 'englishName', 'id'].some(key => {
    const text = normalize(row[key]);
    let i = 0;
    for (const char of text) if (char === needle[i]) i++;
    return i === needle.length;
  });
}

export function operatorCandidates(rows, professions, query = '') {
  return rows.filter(row => (!professions.length || !row.profession || professions.includes(row.profession)) && fuzzyMatch(row, query))
    .sort((a, b) => (b.rarity || 0) - (a.rarity || 0));
}

export const SOURCE_CHOICES = { normal: '普通招募', temporary: '临时招募', assistance: '应急助力' };
export function sourceChoice(source) {
  return source === 'emergency' ? 'assistance' : source === 'squad_002-temporary' ? 'temporary' : source === 'squad_002' ? 'normal' : source || 'normal';
}
