#include "viewer/Results.hpp"
#include <iostream>
#include <sstream>
#include <stdexcept>
using namespace sensor_platform::viewer;
std::string fixture() {
    std::ostringstream s;
    s << "SENSOR_STUDY 1\nSTUDY \"Test\" \"Question?\" \"id\" 20 2\n";
    for(const auto* panel:{"noise","reliability","clutter","convergence","sensor_network"}) {
        s << "PANEL \""<<panel<<"\" \"Title\" \"Axis\"\n";
        for(const auto* metric:{"position_rmse","false_track_samples"}) {
            s << "CHART \""<<panel<<"\" \""<<metric<<"\" \"Metric\" \"m\" \"Definition\" \"Finding\"\n";
            s << "POINT \""<<panel<<"\" \""<<metric<<"\" 0 2 2 1 0.5 0.5 1.5\n";
            s << "POINT \""<<panel<<"\" \""<<metric<<"\" 1 2 0 0 0 0 0\n";
        }
    }
    return s.str()+"END\n";
}
int main() {
    try {
        std::istringstream input(fixture()); const auto data=readStudyResults(input);
        if(data.runs!=20 || data.panels.size()!=5 || data.panels[0].charts[0].points[1].valid!=0) throw std::runtime_error("load mismatch");
        std::string windowsText;
        for (char c : fixture()) { if (c == '\n') windowsText += '\r'; windowsText += c; }
        std::istringstream windowsInput(windowsText);
        if (readStudyResults(windowsInput).runs != 20) throw std::runtime_error("CRLF export mismatch");
        for(int test=0;test<5;++test) {
            auto text=fixture();
            if(test==0) text.resize(text.size()-4);
            if(test==1) text.replace(text.find("20 2"),4,"19 2");
            if(test==2) text.replace(text.find("0.5 1.5"),7,"0.5 0.6");
            if(test==3) text += "trailing\n";
            if(test==4) text.replace(text.find("0 2 2 1"),7,"0 2 3 1");
            bool rejected=false;
            try {std::istringstream bad(text);readStudyResults(bad);} catch(const std::exception&) {rejected=true;}
            if(!rejected) throw std::runtime_error("accepted invalid result data");
        }
        std::cout<<"Results loader checks passed; display model has no simulation dependency\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
