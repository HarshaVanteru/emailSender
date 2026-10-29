export const gmailCategories = [
  { id: 'CATEGORY_PERSONAL', name: 'Primary' },
  { id: 'CATEGORY_PROMOTIONS', name: 'Promotions' },
  { id: 'CATEGORY_SOCIAL', name: 'Social' },
  { id: 'CATEGORY_UPDATES', name: 'Updates' },
  { id: 'CATEGORY_FORUMS', name: 'Forums' },
];

export function isPrimary(labels: string[]): boolean {
  return labels.includes('CATEGORY_PERSONAL')
    && !labels.some(label => ['SPAM', 'TRASH', 'SENT', 'DRAFT'].includes(label)
      || (label.startsWith('CATEGORY_') && label !== 'CATEGORY_PERSONAL'));
}

export function matchesSection(labels: string[], section: string, aiSpam: boolean | null | undefined): boolean {
  if (section === 'TRASH') return labels.includes('TRASH');
  if (labels.includes('TRASH')) return false;
  if (section === 'SPAM') return labels.includes('SPAM');
  if (labels.includes('SPAM')) return false;
  if (section === 'MYBOX') return isPrimary(labels) && aiSpam === false;
  if (section === 'CATEGORY_PERSONAL') return isPrimary(labels);
  if (section.startsWith('CATEGORY_') && labels.some(label => ['SENT', 'DRAFT'].includes(label))) return false;
  return !section || labels.includes(section);
}
