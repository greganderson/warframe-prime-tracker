export type AvailabilityStatus='farmable'|'resurgence'|'special'|'vaulted'|'exclusive'|'unknown';
export interface Part {id:string;name:string;required:number;owned:number;ducats:number;market_median:number|null;availability:AvailabilityStatus}
export type EquipmentType='warframe'|'archwing'|'primary'|'secondary'|'melee'|'archgun'|'companion'|'companion_weapon'|'equipment';
export interface Equipment {id:string;name:string;type:EquipmentType;availability:AvailabilityStatus;mastered:number;ready:boolean;missing_count:number;surplus_sets:number;parts:Part[]}
export interface Relic {id:string;era:string;code:string;availability:AvailabilityStatus}
export interface Reward extends Part {rarity:'common'|'uncommon'|'rare';market_window:string|null;mastered:boolean;set_complete:boolean;part_owned:boolean}
export interface RunColumn extends Relic {rewards:Reward[]}
export interface RunSession {id:string;state:'open'|'confirmed';chosen_item_id:string|null;columns:RunColumn[]}
export interface VoiceRelic {heard:string;relic_id:string|null;options:string[]}
export interface VoiceMessage {text?:string;relics?:VoiceRelic[];done?:boolean;error?:string}
