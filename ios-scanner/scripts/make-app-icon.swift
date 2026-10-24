// Native rasterization of the repository's existing favicon.svg, without third-party assets.
import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
let target=CommandLine.arguments[1]
let ctx=CGContext(data:nil,width:1024,height:1024,bitsPerComponent:8,bytesPerRow:4096,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.noneSkipLast.rawValue)!
ctx.setFillColor(CGColor(red:15/255,green:92/255,blue:85/255,alpha:1))
ctx.fill(CGRect(x:0,y:0,width:1024,height:1024))
ctx.setStrokeColor(CGColor(red:1,green:1,blue:1,alpha:1));ctx.setLineWidth(80);ctx.setLineCap(.square)
ctx.move(to:CGPoint(x:224,y:288));ctx.addLine(to:CGPoint(x:800,y:288));ctx.addLine(to:CGPoint(x:800,y:736));ctx.addLine(to:CGPoint(x:224,y:736));ctx.closePath()
ctx.move(to:CGPoint(x:512,y:736));ctx.addLine(to:CGPoint(x:512,y:544));ctx.move(to:CGPoint(x:512,y:416));ctx.addLine(to:CGPoint(x:512,y:288));ctx.strokePath()
ctx.setFillColor(CGColor(red:1,green:1,blue:1,alpha:1));ctx.fillEllipse(in:CGRect(x:288,y:416,width:128,height:128))
let image=ctx.makeImage()!
let destination=CGImageDestinationCreateWithURL(URL(fileURLWithPath:target) as CFURL,UTType.png.identifier as CFString,1,nil)!
CGImageDestinationAddImage(destination,image,nil)
precondition(CGImageDestinationFinalize(destination))
