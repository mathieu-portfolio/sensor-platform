#include "Results.hpp"
#include <raylib.h>
#include <algorithm>
#include <charconv>
#include <cmath>
#include <fstream>
#include <stdexcept>
#include <iostream>

namespace sensor_platform::viewer {
namespace {
constexpr Color bg{13,20,30,255}, card{21,32,45,255}, ink{228,238,247,255}, muted{145,165,184,255}, grid{45,59,74,255};
constexpr Color palette[]{{74,195,255,255},{85,230,170,255},{255,180,82,255},{198,138,255,255},{255,130,158,255}};
void text(const std::string& s, float x, float y, int size=18, Color color=ink) { DrawText(s.c_str(), static_cast<int>(x), static_cast<int>(y), size, color); }
void wrapped(const std::string& s, float x, float y, float width, int size, Color color, int maxLines=4) {
    std::string line, word;
    int lines=0;
    auto emit=[&] { text(line,x,y,size,color); y+=size+5; line.clear(); ++lines; };
    for (std::size_t i=0; i<=s.size(); ++i) {
        if (i<s.size() && s[i]!=' ') { word+=s[i]; continue; }
        if (!line.empty() && MeasureText((line+" "+word).c_str(),size)>width) { emit(); if (lines>=maxLines) return; }
        if (!line.empty()) line+=' ';
        line+=word; word.clear();
    }
    if (!line.empty() && lines<maxLines) emit();
}
std::string number(double value) { return TextFormat(value>=100 ? "%.0f" : value>=10 ? "%.1f" : "%.2f", value); }
void chart(const ResultChart& c, const std::string& axis, Rectangle box, Color accent, bool details) {
    DrawRectangleRounded(box,.035f,8,card);
    text(c.title,box.x+18,box.y+16,20);
    text(c.unit,box.x+18,box.y+43,14,muted);
    const float left=box.x+55, right=box.x+box.width-24, top=box.y+83;
    const float bottom=box.y+box.height-(details ? 155 : 88);
    double upper=1;
    for (const auto& p:c.points) if(p.valid) upper=std::max(upper,p.mean+p.deviation);
    upper*=1.18;
    auto py=[&](double value) {return bottom-static_cast<float>(value/upper)*(bottom-top);};
    for(int i=0;i<=4;++i) {
        double value=upper*i/4;
        DrawLine(static_cast<int>(left),static_cast<int>(py(value)),static_cast<int>(right),static_cast<int>(py(value)),grid);
        text(number(value),box.x+8,py(value)-6,12,muted);
    }
    Vector2 previous{}; bool hasPrevious=false;
    const double minimum=c.points.front().value, maximum=c.points.back().value;
    for(const auto& p:c.points) {
        const float x=left+12+static_cast<float>((p.value-minimum)/(maximum-minimum))*(right-left-24);
        text(TextFormat("%g",p.value),x-12,bottom+10,14,ink);
        if(!p.valid) {text("no matches",x-30,top+30,12,muted);hasPrevious=false;continue;}
        Vector2 current{x,py(p.mean)};
        if(hasPrevious) DrawLineEx(previous,current,2,Fade(accent,.65f));
        const float high=py(p.mean+p.deviation),low=py(std::max(0.,p.mean-p.deviation));
        DrawLineEx({x,high},{x,low},2,accent);
        DrawLineEx({x-5,high},{x+5,high},2,accent); DrawLineEx({x-5,low},{x+5,low},2,accent);
        DrawCircleV(current,5,accent);
        text(number(p.mean),x-16,high-20,14,accent);
        text(TextFormat("n=%d/%d",p.valid,p.runs),x-25,bottom+32,12,muted);
        if(CheckCollisionPointCircle(GetMousePosition(),current,14)) {
            const std::string tip="Mean "+number(p.mean)+" | SD "+number(p.deviation)+" | range "+number(p.minimum)+" - "+number(p.maximum);
            const float tx=std::clamp(x-150,box.x+8,box.x+box.width-320);
            DrawRectangle(static_cast<int>(tx),static_cast<int>(top-22),312,28,bg);text(tip,tx+5,top-15,12,ink);
        }
        previous=current;hasPrevious=true;
    }
    text(axis,box.x+box.width/2-MeasureText(axis.c_str(),14)/2,box.y+box.height-(details?96:28),14,muted);
    if(details) wrapped(c.definition,box.x+18,box.y+box.height-66,box.width-36,13,muted,3);
}
void draw(const StudyResults& result, int page) {
    const float width=static_cast<float>(GetScreenWidth()),height=static_cast<float>(GetScreenHeight());
    ClearBackground(bg);
    text("SENSOR PLATFORM",28,20,16,palette[0]);text("/  ANALYTICS & RESULTS",215,20,16,muted);
    text(result.question,28,51,20);
    text(TextFormat("%d run executions   |   %d paired seeds / condition   |   5 one-variable comparisons",result.runs,result.seeds),28,85,17,ink);
    text("Persisted offline evaluation  /  Individual scenario playback is a separate viewer mode",28,112,14,muted);
    text("0-5 / arrows: tabs",width-205,112,14,muted);
    const char* tabs[]{"Overview","Noise","Reliability","Clutter","Convergence","Sensor network"};
    for(int i=0;i<6;++i) {
        Rectangle tab{28+i*(width-56)/6,145,(width-68)/6,36};
        DrawRectangleRounded(tab,.15f,4,page==i?Color{33,70,92,255}:card);
        text(tabs[i],tab.x+14,tab.y+10,16,page==i?ink:muted);
    }
    if(page==0) {
        const float w=(width-80)/3,h=(height-285)/2;
        for(int i=0;i<5;++i) {
            const auto& p=result.panels[i];
            Rectangle box{28+(w+12)*(i%3),199+(h+12)*(i/3),w,h};
            auto overview = p.charts.front();
            overview.title = p.title;
            overview.unit = p.charts.front().title + " (" + overview.unit + ")";
            chart(overview,p.axis,box,palette[i],false);
        }
        const float x=28+2*(w+12),y=199+h+12;
        DrawRectangleRounded({x,y,w,h},.035f,8,card);
        text("READING THIS STUDY",x+18,y+18,18,palette[1]);
        wrapped("Dots: condition means. Whiskers: +/- one sample SD, clipped at zero. These are descriptive spreads, not confidence intervals.",x+18,y+53,w-36,15,ink,4);
        wrapped("Select a tab for companion metrics and definitions. Hover a mean to inspect its min/max range.",x+18,y+148,w-36,14,muted,3);
        wrapped("Higher measurement yield includes clutter. False tracks are not false sensor returns.",x+18,y+h-63,w-36,14,palette[2],3);
    } else {
        const auto& p=result.panels[page-1];
        const float w=(width-56-12*(p.charts.size()-1))/p.charts.size();
        for(std::size_t i=0;i<p.charts.size();++i)
            chart(p.charts[i],p.axis,{28+i*(w+12),199,w,height-385},palette[page-1],true);
        wrapped(p.charts.front().finding,28,height-167,width-56,18,ink,2);
        text("Use companion metrics: matched-track RMSE alone can hide missed targets or identity errors.",28,height-109,15,muted);
    }
    text("RMSE: matched-position error (m)   |   Misses: unmatched target samples   |   ID switches: matched identity changes",28,height-60,14,muted);
    text("False tracks: unmatched non-tentative track samples. Fixed layout seed; no statistical significance or causal claims.",28,height-37,14,muted);
}
}
int resultsCommand(int argc,char** argv) {
    if(argc<3) throw std::invalid_argument("--results requires a persisted results.view file");
    int frames=0,page=0; std::string screenshot;
    for(int i=3;i<argc;i+=2) {
        if(i+1>=argc) throw std::invalid_argument("Missing results option value");
        const std::string option=argv[i],value=argv[i+1];
        if(option=="--screenshot") {screenshot=value;continue;}
        int n{};auto parsed=std::from_chars(value.data(),value.data()+value.size(),n);
        if(parsed.ec!=std::errc{} || parsed.ptr!=value.data()+value.size()) throw std::invalid_argument("Invalid results numeric option");
        if(option=="--frames" && n>0) frames=n;
        else if(option=="--page" && n>=0 && n<=5) page=n;
        else throw std::invalid_argument("Unknown or invalid results option");
    }
    std::ifstream input(argv[2]);
    if(!input) throw std::runtime_error("Cannot open persisted study results; run study analysis first");
    const auto result=readStudyResults(input);
    SetConfigFlags(FLAG_WINDOW_RESIZABLE|FLAG_MSAA_4X_HINT|FLAG_WINDOW_HIGHDPI);
    InitWindow(1440,960,"Sensor Platform | Multi-seed analytics results");
    if(!IsWindowReady()) throw std::runtime_error("Cannot initialize results window");
    SetWindowMinSize(1280,900);SetTargetFPS(60);
    int rendered=0;
    while(!WindowShouldClose()) {
        if(IsKeyPressed(KEY_RIGHT)) page=(page+1)%6;
        if(IsKeyPressed(KEY_LEFT)) page=(page+5)%6;
        for(int i=0;i<6;++i) if(IsKeyPressed(KEY_ZERO+i)) page=i;
        if(IsMouseButtonPressed(MOUSE_BUTTON_LEFT) && GetMouseY()>=145 && GetMouseY()<181 && GetMouseX()>=28 && GetMouseX()<GetScreenWidth()-28)
            page=std::clamp(static_cast<int>((GetMouseX()-28)*6.f/(GetScreenWidth()-56)),0,5);
        BeginDrawing();draw(result,page);EndDrawing();
        if(frames && ++rendered>=frames) break;
    }
    if(!screenshot.empty()) {
        Image image=LoadImageFromScreen();bool saved=ExportImage(image,screenshot.c_str());UnloadImage(image);
        if(!saved) {CloseWindow();throw std::runtime_error("Cannot save results screenshot");}
    }
    CloseWindow();
    std::cout<<"Loaded persisted study: "<<result.runs<<" runs; "<<result.seeds<<" seeds/condition; no simulation executed\n";
    return 0;
}
}
