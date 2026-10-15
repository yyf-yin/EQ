export interface Run {data_template_version?:string|null;data_slot_counts?:Record<string,number>;collection_slot_counts?:Record<string,number>;run_id:string;company_input:string;company_name:string;mode:'mock'|'real';status:string;stage:string;limitations:string[];error:string|null;created_at?:string;updated_at?:string;formats?:string[];rules_version?:string;blocks?:{block_id:string;status:string;version:string}[];coverage_counts?:Record<string,number>;batch_counts?:Record<string,number>;runtime?:RuntimeSummary;recovery?:Recovery}
export interface Recovery {
  current_session?:boolean;can_pause?:boolean;
 can_resume:boolean;can_increase_budget:boolean;reason:string;checkpoint_node:string|null;
 saved_units:Record<string,number>;unfinished_units:number;resume_count:number;legacy:boolean;
 budget:{global_call_budget:number;global_token_budget:number;block_call_budget:number;enforce_call_budgets?:boolean;calls_used:number;tokens_used:number;unknown_calls:number};
}

export interface DataSlot {
 slot_id:string;field_id:string;label:string;period:string;segment_id:string|null;bond_id:string|null;detail_id?:string|null;product_name?:string|null;
 state:string;raw_value:string|null;raw_unit:string|null;normalized_value:string|boolean|null;
 normalized_unit:string;source_id:string|null;locator:string|null;reason:string;locked_at:string|null;
 metric_code?:string;requirement?:string;period_start?:string;period_end?:string;period_kind?:string;period_label?:string;
}
export interface DataSlots {
 template_version:string|null;
 latest_interim_period?:string|null;
 groups:{group_id:string;title:string;fields:{field_id:string;label:string;normalized_unit:string;requirement:string}[]}[];
 slots:DataSlot[];
 materials:{slot_id:string;topic:string;state:string;search_count:number;limitations:string[];
  scope?:{subject:string;start_date:string;as_of:string;policy_start_date:string;region:string;linked_segments:string[]};
  directions?:{direction_id:string;label:string;description:string;origin:string;reason:string;required:boolean}[];
  direction_statuses?:Record<string,{status:string;evidence_ids:string[];reason:string}>;
  stop_reason?:string;search_budget?:number;
  search_history?:{query:string;direction_ids:string[];state:string;warnings:string[]}[];
 }[];
 bond_presence:{state:string;quote:string;periods:string[]}[];
}
export interface RuntimeSummary {
 artifact_counts:Record<string,number>;
 usage:{calls:number;running_calls:number;succeeded_calls:number;failed_calls:number;provider_input_tokens:number;provider_output_tokens:number;usage_missing_calls:number;cache_reported_calls?:number;cache_reported_input_tokens?:number;cache_hit_tokens?:number;cache_hit_ratio?:number|null};
 recent_calls:{call_id:string;role:string;model?:string;block_id?:string;attempt?:number;result?:string;started_at?:string;duration_seconds?:number;input_tokens?:number;output_tokens?:number;cache_hit_tokens?:number;cache_miss_tokens?:number;response_model?:string|null;reasoning_tokens?:number}[];
}
export interface Progress {event_id:number;run_id:string;timestamp:string;stage:string;task_name:string;status:string;display_message:string}
export interface Section {section_id:string;title:string;paragraphs:string[];children:Section[];tables:{title:string;columns:string[];rows:string[][]}[];evidence_ids:string[];calculation_ids:string[]}
export interface Report {title:string;mode:string;as_of:string;rules_version?:string;sections:Section[];limitations:string[];charts:{title:string;labels:string[];values:string[];unit:string}[];sources:{source_id:string;title:string;source_url:string|null;locator:string;publication_date:string|null}[];evidence:{evidence_id:string;source_id:string;claim:string;locator:string}[]}
export interface WorkProduct {
 fact_decision_count?:number;
 fact_decisions?:{decision_id:string;group_id:string;identity:Record<string,string|null>;status:string;reason:string;selected_ids:string[];proof_evidence_ids:string[];candidates:{fact_id:string;value:string;unit:string;accounting_basis:string;source_id:string;evidence_id:string}[]}[];
 artifact_type:'work_product';snapshot_id:string;snapshot_time:string;notice:string;run_status:string;final_review_passed:boolean;
 run:{company_input:string;company_name:string;stage:string;error:string|null;mode:string};
 page:number;page_size:number;artifact_count:number;section_count:number;review_count:number;formats:string[];counts:Record<string,number>;
 blocks:{block_id:string;status:string;version:string}[];
 issues:{issue_id:string;severity:string;location:string;rule_id:string;description:string;suggested_fix:string}[];
 missing:{kind:string;id:string;reason:string}[];unavailable:{artifact:string;reason:string}[];notes:string[];
 artifacts:{kind:string;id?:string;section_id?:string;generation_status:string;validation_status:string;version_status:string}[];
 sections:{section_id:string;block_id:string;generation_status:string;validation_status:string;version_status:string;content:Section}[];
 usage:{calls:number;provider_input_tokens:number;provider_output_tokens:number;usage_missing_calls:number;note:string};
}

export interface HumanIssue {
 issue_id:string;signature:string;identity:Record<string,string|null>;reason:string;blocking:boolean;kind:string;status:string;phase:string;feedback_error:string;
 candidates:{fact_id:string;value:string;unit:string;accounting_basis:string;source_id:string;evidence_id:string;quote?:string;title?:string;source_url?:string|null;locator?:string}[];
}
export interface HumanQueue {issues:HumanIssue[];sources:{source_id:string;title:string;source_url?:string|null}[];feedback:Record<string,unknown>[];can_submit:boolean}
export interface ReferenceAttachment {
 attachment_id:string
 filename:string
 size:number
 content_hash:string
 created_at:string
 status:'ready'
 source_count:number
}
export interface ReferenceLimits {max_files:number;max_file_bytes:number;annual_reports_required?:boolean}
