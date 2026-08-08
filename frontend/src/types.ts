export type AvailabilityStatus='farmable'|'resurgence'|'special'|'vaulted'|'exclusive'|'unknown';
export interface Part {id:string;name:string;required:number;owned:number;ducats:number;market_median:number|null;availability:AvailabilityStatus}
export interface Equipment {id:string;name:string;availability:AvailabilityStatus;owned:number;mastered:number;favorite:number;target:number;ready:boolean;missing_count:number;surplus_sets:number;parts:Part[]}
export interface Relic {id:string;era:string;code:string;availability:AvailabilityStatus;owned:number}
export interface Reward extends Part {rarity:'common'|'uncommon'|'rare';market_window:string|null}
export interface RunColumn extends Relic {rewards:Reward[]}
export interface RunSession {id:string;user_slot:number;state:'open'|'confirmed';chosen_item_id:string|null;columns:RunColumn[]}
