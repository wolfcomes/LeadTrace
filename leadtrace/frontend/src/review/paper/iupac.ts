import { z } from 'zod';
import { apiRequest } from '../../api/client';
import { locale } from '../../i18n';

const resultSchema = z.object({smiles:z.string().min(1),molfile:z.string().min(1),resolver:z.string()});
export function resolveIupac(name:string,csrfToken:string|null) {
 return apiRequest('/api/v2/chemistry/resolve-iupac',resultSchema,{method:'POST',body:{name},csrfToken});
}
const english:Record<string,string> = {
 'IUPAC 名称':'IUPAC name',
 '转换并载入编辑器':'Convert and load into editor',
 '正在转换…':'Converting…',
 '转换会替换当前未保存结构；请核对后保存 Draft。':'Conversion replaces the current unsaved structure. Check it before saving a draft.',
 '转换结果已载入，请核对结构及立体化学后保存 Draft。':'Conversion loaded. Check the structure and stereochemistry before saving a draft.',
 '名称无法解析，请检查拼写及完整立体化学标记。':'Could not parse the name. Check spelling and complete stereochemistry descriptors.',
 '本地名称解析器暂不可用，请联系管理员检查安装。':'The local name resolver is unavailable. Ask an administrator to check its installation.',
 '名称转换超时，请简化或检查名称后重试。':'Name conversion timed out. Check or simplify the name and retry.',
 '名称解析器繁忙，请稍后重试。':'The name resolver is busy. Try again shortly.',
 '转换未完成，请检查名称后重试。':'Conversion failed. Check the name and retry.',
 '转换期间内容已变化，请重新转换。':'Content changed during conversion. Convert again.',
};
export function iupacText(value:string) {return locale.value==='en' ? english[value]??value : value;}
