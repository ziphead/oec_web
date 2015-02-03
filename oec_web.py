#import xml.etree.ElementTree as ET
import lxml.etree as ET
import glob
import os
import urllib
import difflib
import copy
import visualizations 
import oec_filters
import datetime
import oec_fields
import threading
import oec_plots
from numberformat import renderFloat, renderText, notAvailableString
from flask import Flask, abort, render_template, send_from_directory, request, redirect, Response

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

class MyOEC:
    OEC_PATH = APP_ROOT+"/open_exoplanet_catalogue/"
    OEC_META_PATH = APP_ROOT+"/oec_meta/"
    def __init__(self):
        print "Parsing OEC ..."
        self.fullxml = "<systems>\n"
        self.planets = []
        self.systems = []
        self.planetXmlPairs = {}
        self.systemXmlPairs = {}

        # Loop over all files and  create new data
        for filename in glob.glob(self.OEC_PATH + "systems/*.xml"):
            # Open file
            f = open(filename, 'rt')
            xml = f.read()
            f.close()
            self.fullxml+=xml
            filename = filename[len(self.OEC_PATH):]
            # Try to parse file
            root = ET.fromstring(xml)
            self.systems.append(root)
            pstars = root.findall("./star")
            for p in root.findall(".//planet"):
                star = None
                for s in pstars:
                    if p in s:
                        star = s
                        break
                xmlPair = (root,p,star,filename)
                self.planets.append(xmlPair)
                name = p.find("./name").text
                self.planetXmlPairs[name] = xmlPair
            self.systemXmlPairs[root.find("./name").text] = (root,None,filename)
        self.fullxml += "</systems>\n"

        print "Parsing OEC META ..."
        with open(self.OEC_META_PATH+"statistics.xml", 'rt') as f:
            self.oec_meta_statistics = ET.parse(f).getroot()
        
        print "Parsing done."



class FlaskApp(Flask):
    def __init__(self, *args, **kwargs):
        super(FlaskApp, self).__init__(*args, **kwargs)
        self.oec = self.getOEC()

    def getOEC(self):
        mydata = threading.local()
        if not hasattr(mydata, "oec"):
            mydata.oec = MyOEC()
        return mydata.oec

app = FlaskApp(__name__)
def isList(value):
    return isinstance(value, list)
def getFirst(value):
    if isList(value):
        return value[0]
    return value
app.jinja_env.filters['islist'] = isList
app.jinja_env.filters['getFirst'] = getFirst


#################

@app.route('/system.html')
def page_planet_redirect():
    planetname = request.args.get("id")
    return redirect("planet/"+planetname, 301)

#################
@app.route('/plot/<plotname>/')
@app.route('/plot/<plotname>')
@app.route('/plot/<plotname>.svg')
def page_plot(plotname):
    oec = app.oec
    if plotname=="discoveryyear":
        return  Response(oec_plots.discoveryyear(oec.oec_meta_statistics),  mimetype='image/svg+xml')
    if plotname=="skypositions":
        return  Response(oec_plots.skypositions(oec.systems),  mimetype='image/svg+xml')
    abort(404)

@app.route('/')
@app.route('/index.html')
def page_main():
    oec = app.oec
    contributors = []
    for c in oec.oec_meta_statistics.findall(".//contributor"):
        contributors.append(c.text)
    commitdate = datetime.datetime.fromtimestamp(int(oec.oec_meta_statistics.find(".//lastcommittimestamp").text))

    return render_template("index.html",
            numplanets=len(oec.planets),
            numsystems=int(oec.oec_meta_statistics.find("./systems").text),
            numconfirmedplanets=int(oec.oec_meta_statistics.find("./confirmedplanets").text),
            numbinaries=int(oec.oec_meta_statistics.find("./binaries").text),
            lastupdate=commitdate.strftime("%c"),
            numcommits=int(oec.oec_meta_statistics.find("./commits").text),
            contributors=contributors,
        )

@app.route('/systems/',methods=["POST","GET"])
def page_systems():
    oec = app.oec
    p = []
    debugtxt = ""
    fields = ["namelink"]
    filters = []
    if "filters" in request.args:
        listfilters = request.args.getlist("filters")
        for filter in listfilters:
            if filter in oec_filters.titles:
                filters.append(filter) 
    if "fields" in request.args:
        listfields = request.args.getlist("fields")
        for field in listfields:
            if field in oec_fields.titles and field!="namelink":
                fields.append(field) 
    else:
        fields += ["mass","radius","massEarth","radiusEarth","numberofplanets","numberofstars"]
    lastfilename = ""
    tablecolour = 0
    for xmlPair in oec.planets:
        if oec_filters.isFiltered(xmlPair,filters):
            continue
        system,planet,star,filename = xmlPair
        if lastfilename!=filename:
            lastfilename = filename
            tablecolour = not tablecolour
        d = {}
        d["fields"] = [tablecolour]
        for field in fields:
            d["fields"].append(oec_fields.render(xmlPair,field))
        p.append(d)
    return render_template("systems.html",
        columns=[oec_fields.titles[field] for field in fields],
        planets=p,
        available_fields=oec_fields.titles,
        available_filters=oec_filters.titles,
        fields=fields,
        filters=filters,
        debugtxt=debugtxt)


@app.route('/webgl.html')
def page_webgl():
    return render_template("webgl.html")


@app.route('/planet/<planetname>')
@app.route('/planet/<planetname>/')
@app.route('/system/<planetname>/')
def page_planet(planetname):
    oec = app.oec
    try:
        xmlPair = oec.planetXmlPairs[planetname]
    except:
        abort(404)
    system,planet,star,filename = xmlPair
    planets=system.findall(".//planet")
    stars=system.findall(".//star")

    systemtable = []
    for row in ["systemname","systemalternativenames","rightascension","declination","distance","distancelightyears","numberofstars","numberofplanets"]:
        systemtable.append((oec_fields.titles[row],oec_fields.render(xmlPair,row)))
    
    planettable = []
    planettablefields = []
    for row in ["name","alternativenames","description","lists","mass","massEarth","radius","radiusEarth","period","semimajoraxis","eccentricity","temperature","discoverymethod","discoveryyear","lastupdate"]:
        planettablefields.append(oec_fields.titles[row])
        rowdata = []
        for p in planets:
            rowdata.append(oec_fields.render((system,p,star,filename),row))
        if len(set(rowdata)) <= 1 and row!="name": # all fields identical:
            rowdata = rowdata[0]
        planettable.append(rowdata)
    
    startable = []
    startablefields = []
    for row in ["starname","staralternativenames","starmass","starradius","starage","starmetallicity","startemperature","starspectraltype","starvisualmagnitude"]:
        startablefields.append(oec_fields.titles[row])
        rowdata = []
        for s in stars:
            rowdata.append(oec_fields.render((system,planet,s,filename),row))
        if len(set(rowdata)) <= 1 and row!="starname": # all fields identical:
            rowdata = rowdata[0]
        startable.append(rowdata)

    references = []
    contributors = []
    with open(oec.OEC_META_PATH+filename, 'rt') as f:
        root = ET.parse(f).getroot()
        for l in root.findall(".//link"):
            references.append(l.text) 
        for c in root.findall(".//contributor"):
            contributors.append((c.attrib["commits"],c.attrib["email"],c.text)) 

    vizsize = visualizations.size(xmlPair)
    vizhabitable = visualizations.habitable(xmlPair)
    vizarchitecture = visualizations.textArchitecture(system)


    return render_template("planet.html",
        system=system,
        planet=planet,
        filename=filename,
        planetname=planetname,
        vizsize=vizsize,
        vizhabitable=vizhabitable,
        architecture=vizarchitecture,
        systemname=oec_fields.render(xmlPair,"systemname"),
        systemtable=systemtable,
        image=(oec_fields.render(xmlPair,"image"),oec_fields.render(xmlPair,"imagedescription")),
        planettablefields=planettablefields,
        planettable=planettable,
        startablefields=startablefields,
        startable=startable,
        references=references,
        contributors=contributors,
        systemcategory=oec_fields.render(xmlPair,"systemcategory"),
        )

def getAttribText(o,a):
    if a in o.attrib:
        return o.attrib[a]
    else:
        return ""

@app.route('/planet/<planetname>/edit/<path:xmlpath>')
def page_planet_editform(planetname,xmlpath):
    oec = app.oec
    try:
        xmlPair = oec.planetXmlPairs[planetname]
    except:
        abort(404)
    system,planet,star,filename = xmlPair
    planetname = planet.find("./name").text
    o = system.find(xmlpath)
    title = ""
    if o.tag in oec_fields.titles:
        title = oec_fields.titles[o.tag]
    return render_template("edit_form_float.html",
        title=title,
        value=o.text,
        planetnameurl=urllib.quote(planetname),
        errorminus=getAttribText(o,"errorminus"),
        errorplus=getAttribText(o,"errorplus"),
        lowerlimit=getAttribText(o,"lowerlimit"),
        upperlimit=getAttribText(o,"upperlimit"),
        xmlpath=xmlpath,
        )

# Nicely indents the XML output
def indent(elem, level=0):
    i = "\n" + level * "\t"
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "\t"
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


editlock = threading.Lock()

@app.route('/planet/<planetname>/submit-edit/<path:xmlpath>',methods=["POST"])
def page_planet_submiteditform(planetname,xmlpath):
    oec = app.oec
    try:
        xmlPair = oec.planetXmlPairs[planetname]
    except:
        abort(404)
    system,planet,star,filename = xmlPair
    planetname = planet.find("./name").text
    new_system = copy.deepcopy(system)
    o = new_system.find(xmlpath)
    attribs = ["errorplus", "errorminus","upperlimit", "lowerlimit"]
    for attrib in attribs:
        if attrib in request.form:
            newv = request.form[attrib]
            if len(newv)==0:
                if attrib in o.attrib:
                    o.attrib.pop(attrib)
            else:
                o.attrib[attrib] = newv
    if "value" in request.form:
        o.text = request.form["value"]
    
    
    indent(new_system)
    diff = difflib.unified_diff(
            ET.tostring(new_system, encoding="UTF-8", xml_declaration=False).split("\n"), 
            ET.tostring(system, encoding="UTF-8", xml_declaration=False).split("\n"), 
            fromfile=filename, 
            tofile=filename,
            lineterm='')
    
    with editlock:
        patchcount = 0
        with open('patch.count') as f:
            try:
                patchcount = int(f.readline())
            except:
                patchcount = 0
        
        # Just for testing. Needs a proper backend.
        with open('patch.count',"w") as f:
            f.write("%i"%(patchcount+1))
        
        with open("patches/%05d.patch"%patchcount, "w") as f:
            f.write('\n'.join(diff))
        with open("patches/%05d.details"%patchcount, "w") as f:
            f.write(request.form["name"]+"\n")
            f.write(request.form["paper"]+"\n")
            f.write(request.remote_addr+"\n")

    return "Thanks for your contribution. We're checking your commit now."


@app.route('/correlations/')
@app.route('/correlations.html')
def page_correlations():
    return render_template("correlations.html")

@app.route('/histogram/')
@app.route('/histogram.html')
def page_histogram():
    return render_template("histogram.html",)

@app.route('/systems.xml')
def page_systems_xml():
    oec = app.oec
    return oec.fullxml

@app.route('/robots.txt')
def page_robots_txt():
    return "User-agent: *\nDisallow:\n"


if __name__ == '__main__':
    app.run(debug=True,threaded=True)
