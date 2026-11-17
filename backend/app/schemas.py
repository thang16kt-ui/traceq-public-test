from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def validated_scope(value):
    allowed=('inspection_session_id','batch_id','product_type_id','line','shift','stage')
    if not isinstance(value,dict): raise ValueError('Phạm vi phải là object')
    for key,item in value.items():
        if key not in allowed: raise ValueError('Bộ lọc không hỗ trợ')
        if not isinstance(item,str) or not item.strip() or len(item)>160: raise ValueError('Giá trị bộ lọc phải là chuỗi không rỗng tối đa 160 ký tự')
        if key.endswith('_id'):
            try: UUID(item)
            except ValueError: raise ValueError('Mã trong bộ lọc phải là UUID')
        value[key]=item.strip()
    return value

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class LoginIn(Input):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    username: str = Field(min_length=1,max_length=80)
    password: str = Field(min_length=1,max_length=256)

class ProductIn(Input):
    sku: str = Field(min_length=1,max_length=80)
    name: str = Field(min_length=1,max_length=200)
    unit_of_measure: str = Field(default='cái',min_length=1,max_length=40)
    supervisor_id: UUID | None = None
    backup_supervisor_id: UUID | None = None
    unit_cost: Decimal | None = Field(default=None,ge=0,max_digits=18,decimal_places=2)
    salvage_value: Decimal | None = Field(default=None,ge=0,max_digits=18,decimal_places=2)
    @model_validator(mode='after')
    def supervisors_differ(self):
        if self.supervisor_id and self.supervisor_id==self.backup_supervisor_id: raise ValueError('Giám sát thay thế phải khác giám sát chính')
        if self.unit_cost is not None and self.salvage_value is not None and self.salvage_value>self.unit_cost: raise ValueError('Giá trị thu hồi không được lớn hơn giá vốn')
        return self

class BatchIn(Input):
    product_type_id: UUID
    lot_code: str = Field(min_length=1,max_length=100)

class DefectTypeIn(Input):
    code: str = Field(min_length=1,max_length=80)
    name: str = Field(min_length=1,max_length=160)

class CatalogChange(Input):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=3,max_length=2000)

class ProductEdit(ProductIn, CatalogChange): pass

class BatchEdit(BatchIn, CatalogChange): pass

class DefectTypeEdit(Input):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=3,max_length=2000)
    code: str = Field(min_length=1,max_length=80)
    name: str = Field(min_length=1,max_length=160)

class SessionIn(Input):
    batch_id: UUID
    line: str = Field(min_length=1,max_length=80)
    shift: str = Field(min_length=1,max_length=80)
    stage: str = Field(min_length=1,max_length=80)
    inspected_count: int | None = Field(default=None,ge=0)
    sample_method: str = Field(default='manual',max_length=160)
    population_key: str | None = Field(default=None,max_length=160)
    started_at: datetime | None = None
    @field_validator('started_at')
    @classmethod
    def tz(cls,v):
        if v and (v.tzinfo is None or v.utcoffset() is None): raise ValueError('Thời điểm phải có múi giờ')
        return v

class SessionPatch(Input):
    row_version: int = Field(ge=1)
    inspected_count: int | None = Field(default=None,ge=0)
    status: Literal['open','closed'] | None = None
    reason: str = Field(min_length=3,max_length=2000)

class DefectIn(Input):
    defect_type_id: UUID
    occurrence_count: int = Field(default=1,ge=1,le=1000000)
    level: Literal['nhe','trung_binh','nang']  # bắt buộc chọn, không có mặc định
    note: str = Field(default='',max_length=2000)
    suspected_cause: str | None = Field(default=None,max_length=2000)
    verified_cause: str | None = Field(default=None,max_length=2000)

class CaseIn(Input):
    inspection_session_id: UUID
    serial_number: str = Field(min_length=1,max_length=100)
    detected_at: datetime | None = None
    note: str = Field(default='',max_length=4000)
    defects: list[DefectIn] = Field(min_length=1,max_length=30)
    @field_validator('detected_at')
    @classmethod
    def tz(cls,v):
        if v and (v.tzinfo is None or v.utcoffset() is None): raise ValueError('Thời điểm phải có múi giờ')
        return v
    @model_validator(mode='after')
    def unique(self):
        if len({d.defect_type_id for d in self.defects}) != len(self.defects): raise ValueError('Mỗi loại lỗi chỉ có một dòng; tăng occurrence_count khi cần')
        return self

class ConfirmIn(Input):
    client_event_id: UUID
    observed_at: datetime
    device_id: str | None = Field(default=None,max_length=160)
    @field_validator('observed_at')
    @classmethod
    def tz(cls,v):
        if v.tzinfo is None or v.utcoffset() is None: raise ValueError('Thời điểm phải có múi giờ')
        return v

class CasePatch(Input):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=3,max_length=2000)
    status: Literal['in_progress','recheck','closed','cancelled'] | None = None
    assigned_to: UUID | None = None
    result: Literal['passed_after_repair','scrapped','other'] | None = None
    note: str | None = Field(default=None,max_length=4000)
    action_taken: str | None = Field(default=None,max_length=2000)
    defects: list[DefectIn] | None = Field(default=None,min_length=1,max_length=30)

class AllocationIn(Input):
    case_defect_id: UUID
    allocated_amount: Decimal = Field(ge=0,max_digits=18,decimal_places=2)

class CostIn(Input):
    category: str = Field(min_length=1,max_length=80)
    amount: Decimal = Field(ge=0,max_digits=18,decimal_places=2)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    cost_status: Literal['actual','estimated']
    source_reference: str = Field(min_length=1,max_length=200)
    allocations: list[AllocationIn] = Field(default_factory=list,max_length=30)
    @model_validator(mode='before')
    @classmethod
    def strings_only(cls,v):
        if isinstance(v,dict):
            if not isinstance(v.get('amount'),str): raise ValueError('amount phải là chuỗi thập phân')
            for a in v.get('allocations',[]):
                if not isinstance(a.get('allocated_amount'),str): raise ValueError('allocated_amount phải là chuỗi thập phân')
        return v

class ScheduleIn(Input):
    name: str = Field(default='Xuất cuối ngày',min_length=1,max_length=120)
    enabled: bool = True
    local_time: str = Field(pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    days_of_week: list[int] = Field(default_factory=lambda:list(range(7)),min_length=1,max_length=7)
    timezone: str = 'Asia/Ho_Chi_Minh'
    period_rule: Literal['previous_day'] = 'previous_day'
    format: Literal['csv','xlsx'] = 'csv'
    destination_id: Literal['local'] = 'local'
    filters: dict = Field(default_factory=dict)
    @field_validator('timezone')
    @classmethod
    def zone(cls,v):
        try: ZoneInfo(v)
        except (ZoneInfoNotFoundError,ValueError): raise ValueError('Múi giờ IANA không hợp lệ')
        return v
    @field_validator('days_of_week')
    @classmethod
    def days(cls,v):
        if len(set(v))!=len(v) or any(d<0 or d>6 for d in v): raise ValueError('Ngày trong tuần: thứ Hai=0 đến Chủ nhật=6, không trùng')
        return sorted(v)
    @field_validator('filters')
    @classmethod
    def filters_valid(cls,v):
        return validated_scope(v)

class SchedulePatch(ScheduleIn):
    row_version: int = Field(ge=1)

class ExportIn(Input):
    period_start: datetime
    period_end: datetime
    schedule_id: UUID | None = None
    scope: dict = Field(default_factory=dict)
    format: Literal['csv','xlsx'] = 'csv'
    revision: int = Field(default=1,ge=1,le=10000)
    @model_validator(mode='after')
    def period(self):
        for t in (self.period_start,self.period_end):
            if t.tzinfo is None or t.utcoffset() is None: raise ValueError('Mốc kỳ phải có múi giờ')
        if self.period_start>=self.period_end: raise ValueError('Kỳ phải có đầu < cuối')
        self.scope=validated_scope(self.scope)
        return self

class RetryIn(Input):
    reason: str = Field(min_length=3,max_length=2000)
