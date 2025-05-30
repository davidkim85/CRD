from zoneinfo import ZoneInfo
from fastapi.exception_handlers import http_exception_handler
from reportlab.lib.utils import ImageReader
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, Image as PlatypusImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import io, aiohttp, os, aiofiles
from datetime import datetime, date
from datetime import timedelta
from collections import defaultdict
from typing import Annotated, Optional, List
from uuid import uuid4
from fastapi import FastAPI, Request, status, Depends, UploadFile, File, HTTPException, Response, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse,JSONResponse
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from sqlalchemy import select, func, desc, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from app.configurations.database import get_async_session
from app.models.Pagination import get_pagination_params, Pagination
from app.models.models import User, Address,Report,ImageReport
from app.schemas.schemas import  AddressForm, ReportForm,ReportRead, GetData, ImageReportCreate
from redis import asyncio as aioredis
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from app.auth.auth import auth_router, get_current_user, verify_global_password_cookie
from app.broker.tasks import process_image
from app.configurations.config import FULLDOMAIN, FOOTER_HEIGHT, MAX_IMAGES_PER_REPORT
from app.utils.exception import RedirectToHomeException
from starlette.exceptions import HTTPException as StarletteHTTPException
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
]


app = FastAPI(middleware=middleware)
app.mount("/static", StaticFiles(directory="static"), name="static")
# Custom 404 handler to redirect to /aut/login
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 404:
        return RedirectResponse(url="/auth/login")
    # For other HTTP exceptions, use Starlette's default handler
    return await http_exception_handler(request, exc)
app.include_router(auth_router,prefix="/auth")
templates = Jinja2Templates(directory="app/templates")
app.mount("/app/uploads", StaticFiles(directory="app/uploads"), name="uploads")
UPLOAD_DIR = "app/uploads/"
os.makedirs(UPLOAD_DIR, exist_ok=True)
favicon_path = "app/uploads/favicon/favicon.ico"

@app.exception_handler(RedirectToHomeException)
async def redirect_to_home_handler(request: Request, exc: RedirectToHomeException):
    return RedirectResponse(url="/")
@app.on_event("startup")
async def startup():
    redis = aioredis.from_url("redis://localhost:6379", encoding="utf-8", decode_responses=True)
    FastAPICache.init(RedisBackend(redis), prefix="cache")

@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return FileResponse(favicon_path)



async def resize_unique_filename(file: UploadFile):
    # Read content to measure size
    content = await file.read()
    file_size = len(content)
    max_file_size = 10 * 1024 * 1024  # 10MB
    if file_size > max_file_size:
        raise HTTPException(status_code=400, detail="File size exceeds the 5MB limit")
    ext = os.path.splitext(file.filename)[-1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="Invalid image format")
    unique_filename = f"{uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, unique_filename)
    # Write the file asynchronously
    async with aiofiles.open(filepath, "wb") as out_file:
        await out_file.write(content)
    # Trigger Celery task with the filename only
    process_image.delay(filepath)
    return filepath




async def get_last_reports(session: AsyncSession = Depends(get_async_session)) -> List[ReportRead]:
    select_query = (select(Report).options(selectinload(Report.user),selectinload(Report.images)).order_by(desc(Report.created)))
    result = await session.execute(select_query)
    reports = result.scalars().all()
    return [ReportRead.model_validate(rpt) for rpt in reports]


async def get_count_of_reports(session: AsyncSession = Depends(get_async_session))->int:
    total_query = select(func.count()).select_from(Report)
    result = await session.execute(total_query)
    return result.scalar_one()


async def get_count_of_users(session: AsyncSession = Depends(get_async_session))->int:
    total_query = select(func.count()).select_from(User)
    result = await session.execute(total_query)
    return result.scalar_one()

async def get_image_count(session: AsyncSession = Depends(get_async_session)) -> int:
    result = await session.execute(select(func.count(ImageReport.id)))
    return result.scalar_one()

async def get_count_of_suspects(session: AsyncSession = Depends(get_async_session))->int:
    total_query = select(func.count()).select_from(Report).where(Report.title=="Suspect")
    result = await session.execute(total_query)
    return result.scalar_one()


async def get_data(count_reports: int = Depends(get_count_of_reports),
                   reports: List[ReportRead] = Depends(get_last_reports),
                   ) -> GetData:
    return GetData(count_reports=count_reports, reports=reports)



async def get_reports(session: AsyncSession = Depends(get_async_session)):
    select_query = select(Report).options(selectinload(Report.user))
    result = await session.execute(select_query)
    return result.scalars().all()
async def get_data_pie_chart(session: AsyncSession) -> tuple[list[str], list[int], list[str]]:
    result = await session.execute(
        select(Report.title, func.count(Report.id), Report.color)
        .group_by(Report.title, Report.color)
        .order_by(func.count(Report.id).desc())
    )
    rows = result.all()
    labels = [row[0] for row in rows]
    values = [row[1] for row in rows]
    colors = [row[2] if row[2] else '#999999' for row in rows]  # Default to gray if no color
    return labels, values, colors

async def get_daily_report_titles(session: AsyncSession, days: int = 7):
    result = await session.execute(
        select(cast(Report.created, Date), Report.title)
        .where(Report.created >= date.today() - timedelta(days=days))
    )

    rows = result.all()

    grouped_titles = defaultdict(lambda: defaultdict(int))  # Nested dictionary for counting titles
    for created, title in rows:
        grouped_titles[created.isoformat()][title] += 1

    # Prepare labels, data, and titles for the chart
    today = date.today()
    labels = [(today - timedelta(days=i)).isoformat() for i in reversed(range(days))]
    values = [sum(grouped_titles[day].values()) for day in labels]
    titles = [grouped_titles.get(day, {}) for day in labels]
    return labels, values, titles
@app.get("/", include_in_schema=False)
async def index_page(
    request: Request,
    user: User = Depends(get_current_user),
    data: GetData = Depends(get_data),
    count_users:int =Depends(get_count_of_users),
    count_images:int=Depends(get_image_count),
    count_suspects:int=Depends(get_count_of_suspects),
    session: AsyncSession = Depends(get_async_session)):
    if user:
        labels, values, colors = await get_data_pie_chart(session)  # Now including colors
        labels1, values1, titles1 = await get_daily_report_titles(session)

        return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "reports": data.reports,
        "count_reports": data.count_reports,
        "count_users": count_users,
        "count_images": count_images,
        "labels": labels,
        "values": values,
        "colors":colors,
        "labels1": labels1,
        "values1": values1,
        "titles1":titles1,
        "count_suspects":count_suspects
    })
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)



@app.get("/profile",include_in_schema=False,dependencies=[Depends(verify_global_password_cookie)])
async def profile_page(request: Request, user: User = Depends(get_current_user),
                       data: GetData = Depends(get_data)):
    if user:
        return templates.TemplateResponse("profile.html",
                                          {"request": request, "user": user, "reports": data.reports,
                                           "count_reports": data.count_reports})
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

@app.get("/team", response_class=HTMLResponse, include_in_schema=False,dependencies=[Depends(verify_global_password_cookie)])
async def team_page(
    request: Request,
    user: User = Depends(get_current_user),
    datas: GetData = Depends(get_data),
    pagination_params: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_async_session)
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    pagination_params["db"] = db  # Use the session from Depends

    pagination = Pagination(model=User, **pagination_params)
    paginated_data = await pagination.paginate()

    return templates.TemplateResponse("team.html", {
        "request": request,
        "user": user,
        "count_reports": datas.count_reports,
        "reports": datas.reports,
        "list_users": paginated_data["items"],
        "current_page": paginated_data["page"],
        "total_pages": paginated_data["pages"],
        "total_users": paginated_data["total"],
        "per_page": pagination_params["per_page"],
        **paginated_data
    })


@app.get("/report", response_class=HTMLResponse, include_in_schema=False,dependencies=[Depends(verify_global_password_cookie)])
async def report_page(
        request: Request,
        user: User = Depends(get_current_user),
        data: GetData = Depends(get_data),
        session: AsyncSession = Depends(get_async_session)
):
    if user:
        # Get current UTC time and calculate 24 hours ago
        now = datetime.utcnow()
        twenty_four_hours_ago = now - timedelta(days=1)

        # Query to get reports, filtering by created_at timestamp
        select_query = select(Report).filter(Report.created >= twenty_four_hours_ago).options(
            selectinload(Report.images))
        result = await session.execute(select_query)
        reports = result.scalars().all()

        locations = []
        for r in reports:
            locations.append({
                "title": r.title,
                "latitude": r.latitude,
                "longitude": r.longitude,
                "icon": r.icon,
                "images": [{"url": img.url} for img in r.images],  # only URL, not UploadFile
            })

        return templates.TemplateResponse(
            "report.html",
            {
                "request": request,
                "user": user,
                "reports": data.reports,
                "count_reports": data.count_reports,
                "locations": locations
            }
        )
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)



@app.post("/file",response_class=HTMLResponse,include_in_schema=False)
async def upload_image(photo: Optional[UploadFile] = File(None), user: User = Depends(get_current_user),
                       session: AsyncSession = Depends(get_async_session)):
    if photo and user:
        photo_path = await resize_unique_filename(photo)
        user.photo = photo_path
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return RedirectResponse(url="/profile", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

@app.post("/address", response_class=RedirectResponse,include_in_schema=False)
async def upload_address(address_create: Annotated[AddressForm, Depends(AddressForm.as_form)],
                         user: User = Depends(get_current_user), session: AsyncSession = Depends(get_async_session)):
    if address_create.street and address_create.city and address_create.country and user:
        if user.address:
            address_update_dict = address_create.model_dump(exclude_unset=True)
            for key, value in address_update_dict.items():
                setattr(user.address, key, value)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return RedirectResponse(url="/profile", status_code=status.HTTP_302_FOUND)
        else:
            address = Address(**address_create.model_dump(), user_id=user.id)
            session.add(address)
            await session.commit()
            await session.refresh(address)
        return RedirectResponse(url="/profile", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)



@app.post("/report", response_class=HTMLResponse, include_in_schema=False)
async def upload_image(
    create_report: Annotated[ReportForm, Depends(ReportForm.as_form)],
    files: List[UploadFile] = File(None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    report = Report(**create_report.model_dump(), user_id=user.id)
    for file in files:
        try:
            photo_path = await resize_unique_filename(file)  # Returns unique filename
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        create_image = ImageReportCreate(url=photo_path)
        image = ImageReport(**create_image.model_dump())
        session.add(image)
        report.images.append(image)
    session.add(report)
    await session.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

@app.get("/team", response_class=HTMLResponse, include_in_schema=False,dependencies=[Depends(verify_global_password_cookie)])
async def team_page(
    request: Request,
    user: User = Depends(get_current_user),
    datas: GetData = Depends(get_data),
    pagination_params: dict = Depends(get_pagination_params),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    # Add db to pagination_params to be used in Pagination
    pagination_params["db"] = datas.db  # Assuming that `datas` provides access to `db` session

    # Instantiate the Pagination class with necessary parameters
    pagination = Pagination(model=User, **pagination_params)
    paginated_data = await pagination.paginate()

    # Return the response with paginated data and other context
    return templates.TemplateResponse("team.html", {
        "request": request,
        "user": user,
        "count_reports": datas.count_reports,
        "reports": datas.reports,
        "list_users": paginated_data["items"],  # Paginated list of users
        "current_page": paginated_data["page"],  # Current page number
        "total_pages": paginated_data["pages"],  # Total number of pages
        "total_users": paginated_data["total"],  # Total number of users
        "per_page": pagination_params["per_page"],  # Pagination limit per page
        **paginated_data
    })

@app.get("/reports", response_class=HTMLResponse, include_in_schema=False, name="reports_page",dependencies=[Depends(verify_global_password_cookie)])
async def reports_page(
        request: Request,
        user: User = Depends(get_current_user),
        datas: GetData = Depends(get_data),
        pagination_params: dict = Depends(get_pagination_params),  # Use refactored dependency
        page: int = Query(1, ge=1),
        search: str = Query("", alias="search"),
        sort_by: str = Query("created"),
        sort_order: str = Query("desc"),
        db: AsyncSession = Depends(get_async_session)
):
    if user:
        # Add db to pagination_params, so it's passed in Pagination
        pagination_params["db"] = db

        # Paginate reports using the adjusted dependency (no need to pass search, sort_by, and sort_order here)
        pagination = Pagination(model=Report, **pagination_params)
        data = await pagination.paginate()

        # Return the reports page with paginated data
        return templates.TemplateResponse("reports.html", {
            "request": request,
            "user": user,
            "reports": data["items"],
            "count_reports": datas.count_reports,
            "search": search,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "current_page": page,
            "total_pages": data["pages"],
            "total_reports": data["total"],
            **data
        })

    return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)


@app.get("/map2", response_class=HTMLResponse, include_in_schema=False,dependencies=[Depends(verify_global_password_cookie)])
async def map_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
    data = Depends(get_data),
    session: AsyncSession = Depends(get_async_session),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    current_date = date.today()

    query = select(Report).options(selectinload(Report.images))
    if start_date:
        query = query.where(Report.created >= start_date)
    if end_date:
        query = query.where(Report.created <= end_date)

    result = await session.execute(query)
    locations = result.scalars().all()

    # Extract types/categories for filtering, assuming you have loc.category
    # Fallback to title if category doesn't exist
    def get_type(loc):
        return getattr(loc, 'category', None) or loc.title

    types = sorted(set(get_type(loc) for loc in locations))

    # Compute counts by type for badges
    counts_by_type = {t: sum(1 for loc in locations if get_type(loc) == t) for t in types}
    counts_by_type['all'] = len(locations)

    # Build GeoJSON
    locations_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [loc.longitude, loc.latitude]
                },
                "properties": {
                    "name": loc.title,
                    "type": get_type(loc),
                    "icon_url": loc.icon,
                    "photo": loc.images[0].url if loc.images else "/static/img/default.jpg"
                }
            }
            for loc in locations
        ]
    }

    return templates.TemplateResponse("map2.html", {
        "request": request,
        "locations_geojson": locations_geojson,
        "locations": locations,
        "types": types,
        "counts_by_type": counts_by_type,
        "user": user,
        "reports": data.reports,
        "count_reports": data.count_reports,
        "start_date": start_date,
        "end_date": end_date,
        "current_date": current_date
    })
@app.get("/map", response_class=HTMLResponse, include_in_schema=False,dependencies=[Depends(verify_global_password_cookie)])
async def map_page(
    request: Request,
    user: User = Depends(get_current_user),
    data: GetData = Depends(get_data),
    session: AsyncSession = Depends(get_async_session),
    start_date: datetime = Query(None),
    end_date: datetime = Query(None)
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    current_date = date.today()
    query = select(Report).options(selectinload(Report.images))
    if start_date:
        query = query.where(Report.created >= start_date)
    if end_date:
        query = query.where(Report.created <= end_date)

    result = await session.execute(query)
    locations = result.scalars().all()
    types = sorted(set(loc.title for loc in locations))

    return templates.TemplateResponse("map.html", {
        "request": request,
        "locations": [
            {
                "name": loc.title,
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "icon_url": loc.icon,
                "type": loc.title,
                "photo": loc.images[0].url if loc.images else "/static/img/default.jpg"
            } for loc in locations
        ],
        "types": types,
        "user": user,
        "reports": data.reports,
        "count_reports": data.count_reports,
        "start_date": start_date,
        "end_date": end_date,
        "current_date": current_date
    })




logo_path = os.path.join(UPLOAD_DIR, "logo/golani.png")  # Adjust path as needed
logo_image = ImageReader(logo_path)

def add_header(canvas, doc):
    canvas.saveState()

    # Background bar for header
    canvas.setFillColor(HexColor("#4B8BBE"))
    canvas.rect(0, A4[1] - 50, A4[0], 50, fill=1, stroke=0)

    # Draw logo image on left side of header
    logo_width = 40  # in points
    logo_height = 40  # in points
    # Position: 10 pts from left, top aligned inside the 50 pt header bar
    canvas.drawImage(logo_image, 10, A4[1] - 45, width=logo_width, height=logo_height, mask='auto')

    # Header title next to logo
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(60, A4[1] - 35, "24-Hour Report Summary")

    # Date/time right-aligned
    now_israel = datetime.now(ZoneInfo("Asia/Jerusalem"))
    date_text = now_israel.strftime("Israel Time: %H:%M:%S %d-%m-%Y")
    canvas.setFont("Helvetica", 10)
    canvas.drawRightString(A4[0] - 40, A4[1] - 30, date_text)

    canvas.restoreState()

def add_footer(canvas, doc):
    page_num_text = f"Page {canvas.getPageNumber()}"

    now_israel = datetime.now(ZoneInfo("Asia/Jerusalem"))
    footer_text = f"Generated by www.davidka.co.il • {now_israel.strftime('Israel Time: %H:%M:%S %d-%m-%Y')}"

    canvas.saveState()

    # Footer background bar (height 30pt, customize color as you like)
    footer_height = 30
    canvas.setFillColor(HexColor("#4B8BBE"))  # Same blue as header or choose your own
    canvas.rect(0, 0, A4[0], footer_height, fill=1, stroke=0)

    # Footer text color
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 9)

    # Text left aligned
    canvas.drawString(40, 10, footer_text)
    # Page number right aligned
    canvas.drawRightString(A4[0] - 40, 10, page_num_text)

    canvas.restoreState()


def add_header_footer(canvas, doc):
    add_header(canvas, doc)
    add_footer(canvas, doc)


@app.get("/generate-pdf")
async def generate_pdf(user: User = Depends(get_current_user),session: AsyncSession = Depends(get_async_session)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    now = datetime.utcnow()
    yesterday = now - timedelta(hours=24)

    try:
        result = await session.execute(
            select(Report)
            .options(selectinload(Report.images))
            .where(Report.created >= yesterday)
            .order_by(Report.created.desc())
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    reports = result.scalars().unique().all()
    buffer = io.BytesIO()

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        title="24-Hour Report Summary",
        author=f"{FULLDOMAIN} PDF Generator"
    )

    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin + FOOTER_HEIGHT,  # leave space for footer
        doc.width,
        doc.height - FOOTER_HEIGHT - 50,  # leave space for header (50pt)
        id="normal"
    )

    template = PageTemplate(id="header_footer_template", frames=frame, onPage=add_header_footer)
    doc.addPageTemplates([template])

    styles = getSampleStyleSheet()
    elements = []

    report_count = 0
    image_count = 0

    if not reports:
        elements.append(Paragraph("No reports found in the last 24 hours.", styles["Normal"]))
    else:
        async with aiohttp.ClientSession() as http_session:
            for report in reports:
                report_count += 1
                data = [
                    ["Title", report.title],
                    ["Location", f"({report.latitude}, {report.longitude})"],
                    ["Created", report.created.strftime('%H:%M:%S %d-%m-%Y ')],
                ]
                table = Table(data, colWidths=[70 * mm, 100 * mm])
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BOX", (0, 0), (-1, -1), 0.25, colors.black),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ]))
                elements.append(table)
                elements.append(Spacer(1, 6))
                for i, image in enumerate(report.images):
                    if i >= MAX_IMAGES_PER_REPORT:
                        break
                    if image.url:
                        try:
                            async with http_session.get(FULLDOMAIN + image.url) as resp:
                                if resp.status == 200:
                                    img_data = await resp.read()
                                    img_io = io.BytesIO(img_data)
                                    # Bigger image size here
                                    img = PlatypusImage(img_io, width=120 * mm, height=90 * mm)
                                    elements.append(img)
                                    elements.append(Spacer(1, 6))
                                    image_count += 1
                                else:
                                    elements.append(Paragraph(f"<i>Image failed: status {resp.status}</i>", styles["Normal"]))
                        except Exception as e:
                            elements.append(Paragraph(f"<i>Error loading image: {e}</i>", styles["Normal"]))

                elements.append(Spacer(1, 18))

    # Summary Table
    elements.append(Paragraph("Summary", styles["Heading2"]))
    summary_data = [["Total Reports", str(report_count)], ["Total Images", str(image_count)]]
    summary_table = Table(summary_data, colWidths=[70 * mm, 100 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.darkgrey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    elements.append(summary_table)

    doc.build(elements)
    buffer.seek(0)

    return Response(
        content=buffer.read(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline; filename=last_24h_reports.pdf",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@app.post("/reports/{report_id}/delete")
async def delete_report(
    report_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(select(Report).options(selectinload(Report.images)).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    for image in report.images:
        relative_path = image.url.replace("app/uploads/", "").lstrip("/")
        file_path = os.path.join(UPLOAD_DIR, relative_path)
        os.remove(file_path)
    await session.delete(report)
    await session.commit()
    return RedirectResponse(url="/reports", status_code=status.HTTP_303_SEE_OTHER)



