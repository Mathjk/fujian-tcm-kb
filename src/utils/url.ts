export const BASE = import.meta.env.BASE_URL.replace(/\/$/, '');

export function u(path: string): string {
  return BASE + '/' + path.replace(/^\//, '');
}

export const BOOK_SHORT: Record<string, string> = {
  'fujian-zhongcaoyao-vol1': '闽草一',
  'caise-tupu-1992': '彩图谱',
  'suren-tuji-2010': '速认集',
  'fangxuan-vol3-1986': '方选三',
  'fangxuan-2': '方选二',
  'fujian-chufang-1971': '闽处方',
};

export const BOOK_FULL: Record<string, string> = {
  'fujian-zhongcaoyao-vol1': '《福建中草药·第一册》',
  'caise-tupu-1992': '《常用中草药彩色图谱》',
  'suren-tuji-2010': '《中草药速认图集》',
  'fangxuan-vol3-1986': '《中草药方选·第三集》',
  'fangxuan-2': '《福建中草药方选2》',
  'fujian-chufang-1971': '《福建中草药处方》',
};
